import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from sqlalchemy import select
from src.models import Job, Report, Delivery, Calibration
from src.config.settings import ARTIFACT_DIR

# 新简报只收确认的缺陷带；待复核点与孤立点需要人工确认后才可并入。
CONFIRMED_KEYS = [('band', '确认缺陷带'), ('count', '缺陷点数'), ('from_km', '起点km'), ('to_km', '终点km'), ('span_m', '跨度m'), ('max_severity', '最高等级'), ('mean_lateral', '平均横偏mm'), ('review', '复核动作')]


def create(db, data):
    j=db.get(Job,data.job_id)
    if not j or j.status!='completed' or not j.approved:
        raise HTTPException(409,'请先选择已完成且获批准的分析结果')
    latest=current_version(db,j.dataset_id)
    if j.calibration_version!=latest:
        raise HTTPException(409,f'该试验基于里程校准v{j.calibration_version}，批次当前为v{latest}；请基于最新校准重新计算后再建立简报')
    r=Report(name=data.name, job_id=j.id, destination=data.destination, interval_seconds=data.interval_seconds, next_run=time.time()+data.delay_seconds, enabled=True, calibration_version=j.calibration_version, suspended_reason='')
    db.add(r); db.flush()
    return r


def current_version(db, dataset_id):
    return db.scalar(select(Calibration.version).where(Calibration.dataset_id==dataset_id,Calibration.active==True).order_by(Calibration.version.desc()).limit(1)) or 0


def stopped_reason(report, latest):
    """旧简报静默停在旧校准上：校准一旦更新，尚未发布且引用旧版本的简报停止发布。"""
    if report.calibration_version != latest:
        return f'简报基于里程校准v{report.calibration_version}，批次当前为v{latest}；请基于最新校准重新计算并建立新简报。'
    return ''


def deliver(db, report):
    j=db.get(Job,report.job_id)
    if not j or not j.approved: return None
    if report.suspended_reason: return None
    latest=current_version(db,j.dataset_id)
    if report.calibration_version != latest:
        report.enabled=False
        report.suspended_reason=stopped_reason(report,latest)
        return None
    out=io.StringIO()
    out.write('﻿')
    writer=csv.writer(out)
    def safe(v):
        if isinstance(v,(int,float)) and not isinstance(v,bool): return v
        text=str(v)
        return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
    table=j.result.get('table',{})
    writer.writerow([safe(label) for _,label in CONFIRMED_KEYS])
    # 仅确认缺陷带入简报；旧计算结果里若混有“孤立/稀疏点”汇总行也排除。
    for row in table.get('rows',[]):
        if not str(row.get('band','')).startswith('缺陷带'): continue
        writer.writerow([safe(row.get(key,'')) for key,_ in CONFIRMED_KEYS])
    data=out.getvalue().encode('utf-8')
    delivery=Delivery(report_id=report.id, created_at=time.time(), checksum=hashlib.sha256(data).hexdigest(), filename='', destination=report.destination)
    db.add(delivery); db.flush()
    delivery.filename=f'report-{report.id}-delivery-{delivery.id}.csv'
    os.makedirs(ARTIFACT_DIR,exist_ok=True)
    with open(os.path.join(ARTIFACT_DIR,delivery.filename),'wb') as f:f.write(data)
    with open(os.path.join(ARTIFACT_DIR,delivery.filename+'.json'),'w') as f: json.dump({'job':j.name,'params':j.params,'calibration':j.calibration_snapshot,'result':j.result,'checksum':delivery.checksum},f,ensure_ascii=False,allow_nan=False)
    report.next_run=time.time()+report.interval_seconds
    return delivery


def suspend_stale(db, dataset_id):
    """校准更新后调用：把引用旧校准、尚未发布的简报停止发布，历史归档仍可查。"""
    latest=current_version(db,dataset_id)
    changed=[]
    for report in db.scalars(select(Report).where(Report.enabled==True)):
        job=db.get(Job,report.job_id)
        if job is None or job.dataset_id!=dataset_id: continue
        reason=stopped_reason(report,latest)
        if reason:
            report.enabled=False; report.suspended_reason=reason; changed.append(report)
    return changed
