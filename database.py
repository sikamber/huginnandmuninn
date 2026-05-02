import os
import sqlite3

from sqlmodel import SQLModel, create_engine

db_path = os.environ.get("DATABASE_PATH", "app.db")
engine = create_engine(f"sqlite:///{db_path}")

_MIGRATIONS = [
    ("task", "threat_level", "VARCHAR NOT NULL DEFAULT 'medium'"),
    ("task", "context_tags", "TEXT"),
    ("task", "next_user_review", "DATE"),
    ("task", "user_review_notes", "TEXT"),
    ("task", "next_ai_review", "DATE"),
    ("task", "ai_review_notes", "TEXT"),
    ("quest", "next_user_review", "DATE"),
    ("quest", "user_review_notes", "TEXT"),
    ("quest", "next_ai_review", "DATE"),
    ("quest", "ai_review_notes", "TEXT"),
    ("questline", "next_user_review", "DATE"),
    ("questline", "user_review_notes", "TEXT"),
    ("questline", "next_ai_review", "DATE"),
    ("questline", "ai_review_notes", "TEXT"),
    ("inboxitem", "threat_level", "VARCHAR NOT NULL DEFAULT 'medium'"),
]


def create_tables():
    SQLModel.metadata.create_all(engine)
    conn = sqlite3.connect(db_path)
    task_cols = [row[1] for row in conn.execute("PRAGMA table_info(task)").fetchall()]
    if "evaluated" in task_cols:
        conn.execute("UPDATE task SET status='evaluated' WHERE evaluated=1 AND status='done'")
        conn.execute("ALTER TABLE task DROP COLUMN evaluated")
    for table, column, definition in _MIGRATIONS:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()
    conn.close()
