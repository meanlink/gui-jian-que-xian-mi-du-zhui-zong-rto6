import math, time
from fastapi import HTTPException
from sqlalchemy import select
from src.models import Dataset
from src.services.business import metadata, MAX_POINT_ERROR_M
from src.utils.serialization import checksum


def _required_columns():
    return [c for c in metadata()['columns'] if c.get('required', True)]


def create(db, data):
    name=data.name.strip()
    if len(name)<2: raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(Dataset).where(Dataset.name==name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')
    for index,row in enumerate(data.records):
        for c in _required_columns():
            value=row.get(c['key'])
            if value is None or value=='': raise HTTPException(422, f'第 {index+1} 行缺少字段 {c["label"]}')
            if c['type']=='number':
                try:
                    if isinstance(value,bool) or not math.isfinite(float(value)): raise ValueError()
                    row[c['key']]=float(value)
                except (TypeError, ValueError, OverflowError): raise HTTPException(422, f'第 {index+1} 行 {c["label"]} 必须为有限数值')
        run=row.get('run_id')
        if run is not None and run!='':
            if not isinstance(run,str) or len(run.strip())>60: raise HTTPException(422, f'第 {index+1} 行 车次 须为 1~60 个字符')
            row['run_id']=run.strip()
        elif 'run_id' in row:
            row.pop('run_id')
        error=row.get('mileage_error_m')
        if error is not None and error!='':
            try:
                if isinstance(error,bool) or not math.isfinite(float(error)): raise ValueError()
                error=float(error)
            except (TypeError, ValueError, OverflowError): raise HTTPException(422, f'第 {index+1} 行 单点里程误差 必须为有限数值')
            if not 0<=error<=MAX_POINT_ERROR_M: raise HTTPException(422, f'第 {index+1} 行 单点里程误差须在 0~{MAX_POINT_ERROR_M:g} 米之间')
            row['mileage_error_m']=error
        elif 'mileage_error_m' in row:
            row.pop('mileage_error_m')
    d=Dataset(name=name, source=data.source, records=data.records, checksum=checksum(data.records), created_at=time.time())
    db.add(d); db.flush()
    return d
