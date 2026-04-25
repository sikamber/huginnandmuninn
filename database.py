import os
import sqlite3

from sqlmodel import SQLModel, create_engine

db_path = os.environ.get("DATABASE_PATH", "app.db")
engine = create_engine(f"sqlite:///{db_path}")

_MIGRATIONS = [
    ("task", "threat_level", "VARCHAR NOT NULL DEFAULT 'medium'"),
    ("task", "context_tags", "TEXT"),
    ("task", "evaluated", "BOOLEAN NOT NULL DEFAULT 0"),
]


def create_tables():
    SQLModel.metadata.create_all(engine)
    conn = sqlite3.connect(db_path)
    for table, column, definition in _MIGRATIONS:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()
    conn.close()
