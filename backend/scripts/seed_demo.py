import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit, Calibration
from src.services.business import metadata, seed_records, analyze
from src.services.reports import deliver
from src.utils.security import hash_password
from src.utils.serialization import checksum
def seed():
    migrate()
    with Session() as db:
        for role,name in [('admin','林知 · 业务负责人'),('analyst','陈舟 · 分析员'),('viewer','周禾 · 观察员')]:
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password=hash_password('Demo123!')))
        db.flush()
        m=metadata()
        d=db.scalar(select(Dataset).where(Dataset.name==m['dataset_name']))
        if not d:
            rows=seed_records()
            d=Dataset(name=m['dataset_name'],source=m['short']+'-202611.csv',records=rows,checksum=checksum(rows),created_at=time.time())
            db.add(d); db.flush()
        if not db.scalar(select(Calibration).where(Calibration.dataset_id==d.id)):
            db.add(Calibration(dataset_id=d.id,version=1,default_offset_m=0.0,run_offsets={},note='基线里程校准',active=True,created_at=time.time()))
            db.flush()
        calibration=db.scalar(select(Calibration).where(Calibration.dataset_id==d.id,Calibration.active==True)) or db.scalar(select(Calibration).where(Calibration.dataset_id==d.id).order_by(Calibration.version.desc()).limit(1))
        if calibration is None:
            calibration=Calibration(dataset_id=d.id,version=1,default_offset_m=0.0,run_offsets={},note='基线里程校准',active=True,created_at=time.time())
            db.add(calibration);db.flush()
        if not db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name'])):
            snapshot={'version':calibration.version,'default_offset_m':calibration.default_offset_m,'run_offsets':dict(calibration.run_offsets or {}),'applied':False}
            params={p['key']:p['default'] for p in m.get('parameters',[])}
            result=analyze(d.records,params,snapshot)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            admin=db.scalar(select(User).where(User.role=='admin'))
            j=Job(name='基线复核 · '+m['name'],dataset_id=d.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-3600,finished_at=time.time()-3595,approved=True,calibration_version=calibration.version,calibration_snapshot=snapshot)
            db.add(j);db.flush()
            r=Report(name='每日业务复核简报',job_id=j.id,destination='业务复核组 · 本地收件箱',interval_seconds=86400,next_run=time.time()+86400,enabled=True,calibration_version=calibration.version)
            db.add(r);db.flush();deliver(db,r)
            db.add(Audit(actor='seed',action='demo.baseline',detail={'dataset':d.id,'calibration':calibration.version},at=time.time()))
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in [User,Dataset,Job,Report,Delivery,Audit]}
        print(json.dumps(counts,ensure_ascii=False))
        return counts
if __name__=='__main__':seed()
