import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import analyze
from src.services.reports import deliver
from src.services.audit import record
logging.basicConfig(level=logging.INFO)


def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        # 快照在创建任务时固定；计算中断后重新执行仍使用同一套校准，不会混入新版本。
        snapshot=j.calibration_snapshot or {}
        try:
            d=db.get(Dataset,j.dataset_id)
            if not snapshot:
                # 升级前创建的旧任务没有校准快照，按执行时的当前版本补齐并留档。
                from src.services import calibrations
                snapshot=calibrations.snapshot(calibrations.current(db,d.id))
                j.calibration_snapshot=snapshot
                j.calibration_version=snapshot['version']
                db.flush()
            result=analyze(d.records,j.params,snapshot)
            json.dumps(result,allow_nan=False)
            j.calibration_version=result['calibration']['version']
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id,'calibration':j.calibration_version})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()


def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()


def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    # 恢复时保留任务创建时固定的校准快照，重新计算仍取同一版本。
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id,'calibration':j.calibration_version})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)


if __name__=='__main__':main()
