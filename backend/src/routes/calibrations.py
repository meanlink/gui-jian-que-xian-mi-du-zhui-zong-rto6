from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Dataset
from src.middlewares.auth import current_user, admin_only
from src.services import calibrations
from src.services.audit import record
from src.schemas.calibration import CalibrationInput
router=APIRouter(prefix='/datasets')


@router.get('/{id}/calibrations')
def listing(id:int,db=Depends(get_db),u=Depends(current_user)):
    if not db.get(Dataset,id): raise HTTPException(404,'数据批次不存在')
    return {'current':calibrations.dict_for(calibrations.current(db,id)),'versions':[calibrations.dict_for(item) for item in calibrations.iterations(db,id)]}


@router.post('/{id}/calibrations',status_code=201)
def update(id:int,data:CalibrationInput,db=Depends(get_db),u=Depends(admin_only)):
    if not db.get(Dataset,id): raise HTTPException(404,'数据批次不存在')
    calibration=calibrations.apply_update(db,id,data.default_offset_m,data.run_offsets,data.note,u.id)
    from src.services.reports import suspend_stale
    suspended=suspend_stale(db,id)
    record(db,u.email,'calibration.update',{'dataset':id,'version':calibration.version,'suspended_reports':[r.id for r in suspended]})
    db.commit()
    return {'current':calibrations.dict_for(calibration),'versions':[calibrations.dict_for(item) for item in calibrations.iterations(db,id)],'suspended_reports':len(suspended)}
