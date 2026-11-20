from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models

# 轻量增量迁移：create_all 只建缺失的表，已存在表的新列在此补齐。
ADDED_COLUMNS = [
    ('jobs', 'calibration_version', 'INTEGER NOT NULL DEFAULT 0'),
    ('jobs', 'calibration_snapshot', 'JSON'),
    ('reports', 'calibration_version', 'INTEGER NOT NULL DEFAULT 0'),
    ('reports', 'suspended_reason', "VARCHAR(300) NOT NULL DEFAULT ''"),
]


def migrate():
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            if not inspector.has_table(table):
                continue
            existing = {c['name'] for c in inspector.get_columns(table)}
            if column in existing:
                continue
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
            if ddl == 'JSON' and engine.dialect.name != 'postgresql':
                conn.execute(text(f"UPDATE {table} SET {column} = '{{}}' WHERE {column} IS NULL"))


if __name__ == '__main__':
    migrate()
