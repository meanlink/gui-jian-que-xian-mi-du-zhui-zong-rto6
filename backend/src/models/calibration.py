from sqlalchemy import String, Double, JSON, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Calibration(Base):
    """一次完整的里程校准版本；更新即新增版本，旧版本只读保留。"""
    __tablename__ = 'calibrations'
    __table_args__ = (UniqueConstraint('dataset_id', 'version', name='uq_calibration_dataset_version'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    version: Mapped[int] = mapped_column(default=1)
    default_offset_m: Mapped[float] = mapped_column(Double, default=0.0)
    run_offsets: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(String(300), default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    created_at: Mapped[float] = mapped_column(Double)
