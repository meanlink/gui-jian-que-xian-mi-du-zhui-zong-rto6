def checksum(value):
    import hashlib, json
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}


def job_dict(j):
    data={k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at','calibration_version']}
    data['calibration_snapshot']=getattr(j,'calibration_snapshot',{}) or {}
    return data


def report_dict(r):
    data={k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled','calibration_version']}
    data['suspended_reason']=getattr(r,'suspended_reason','') or ''
    return data


def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
