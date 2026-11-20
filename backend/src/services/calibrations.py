import time, math
from fastapi import HTTPException
from sqlalchemy import select
from src.models import Calibration, Dataset
from src.services.business import MAX_OFFSET_M


def _number(value, label):
    try:
        if isinstance(value, bool):
            raise ValueError()
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(422, f'{label}必须是有效数值') from exc
    if not math.isfinite(number) or abs(number) > MAX_OFFSET_M:
        raise HTTPException(422, f'{label}须在 ±{MAX_OFFSET_M:g} 米内')
    return round(number, 2)


def normalized(default_offset_m, run_offsets):
    if run_offsets is None:
        run_offsets = {}
    if not isinstance(run_offsets, dict):
        raise HTTPException(422, '车次偏移须为“车次 → 偏移米”的对象')
    if len(run_offsets) > 200:
        raise HTTPException(422, '车次偏移条目过多')
    clean = {}
    for key, value in run_offsets.items():
        run = str(key).strip()
        if not run or len(run) > 60:
            raise HTTPException(422, '车次编号须为 1~60 个字符')
        clean[run] = _number(value, f'车次 {run} 的偏移')
    return _number(default_offset_m, '共同偏移'), clean


def iterations(db, dataset_id):
    return list(db.scalars(select(Calibration).where(Calibration.dataset_id == dataset_id).order_by(Calibration.version.desc())))


def current(db, dataset_id):
    versions = iterations(db, dataset_id)
    for item in versions:
        if item.active:
            return item
    return None


def snapshot(item):
    if item is None:
        return {'version': 0, 'default_offset_m': 0.0, 'run_offsets': {}, 'applied': False}
    return {'version': item.version, 'default_offset_m': item.default_offset_m, 'run_offsets': dict(item.run_offsets or {}), 'applied': bool(abs(item.default_offset_m) > 0 or any(abs(value) > 0 for value in (item.run_offsets or {}).values()))}


def apply_update(db, dataset_id, default_offset_m, run_offsets, note, user_id):
    default_offset, clean = normalized(default_offset_m, run_offsets)
    # 锁住批次行，串行化校准更新；试验创建同样读取该行锁，故只能看到一整套版本。
    db.scalar(select(Dataset).where(Dataset.id == dataset_id).with_for_update())
    latest = db.scalar(select(Calibration.version).where(Calibration.dataset_id == dataset_id).order_by(Calibration.version.desc()).limit(1)) or 0
    for item in db.scalars(select(Calibration).where(Calibration.dataset_id == dataset_id, Calibration.active == True)):
        item.active = False
    calibration = Calibration(dataset_id=dataset_id, version=int(latest) + 1, default_offset_m=default_offset, run_offsets=clean, note=str(note or '')[:300], active=True, created_by=user_id, created_at=time.time())
    db.add(calibration)
    db.flush()
    return calibration


def resolve_for_new_job(db, dataset_id):
    """创建试验时一次性读取当前校准快照；并发更新时事务内只有一套版本可用。"""
    item = current(db, dataset_id)
    return item, snapshot(item)


def dict_for(item):
    if item is None:
        return None
    return {'id': item.id, 'dataset_id': item.dataset_id, 'version': item.version, 'default_offset_m': item.default_offset_m, 'run_offsets': dict(item.run_offsets or {}), 'note': item.note, 'active': item.active, 'created_by': item.created_by, 'created_at': item.created_at}
