from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Column
from sqlalchemy import JSON
from sqlmodel import Field, Session, SQLModel, col, select

from database import engine


class Task(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    title: str
    description: str | None = None
    status: str = "todo"  # todo | in_progress | done | evaluated
    due_date: date | None = None
    deadline_type: str | None = None
    defer_until: date | None = None
    energy: str | None = None
    recurrence: int | None = None
    next_user_review: date | None = None
    user_review_notes: str | None = None
    next_ai_review: date | None = None
    ai_review_notes: str | None = None
    notes: str | None = None
    size: int | None = None
    threat_level: str = "medium"
    quest_id: str | None = Field(default=None, foreign_key="quest.id")
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None
    context_tags: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))


class TaskStore:
    def create(
        self,
        title: str,
        description: str | None = None,
        due_date: date | None = None,
        quest_id: str | None = None,
        deadline_type: str | None = None,
        defer_until: date | None = None,
        energy: str | None = None,
        recurrence: int | None = None,
        next_user_review: date | None = None,
        user_review_notes: str | None = None,
        next_ai_review: date | None = None,
        ai_review_notes: str | None = None,
        size: int | None = None,
        threat_level: str = "medium",
    ) -> Task:
        task = Task(
            title=title,
            description=description,
            due_date=due_date,
            quest_id=quest_id,
            deadline_type=deadline_type,
            defer_until=defer_until,
            energy=energy,
            recurrence=recurrence,
            next_user_review=next_user_review,
            user_review_notes=user_review_notes,
            next_ai_review=next_ai_review,
            ai_review_notes=ai_review_notes,
            size=size,
            threat_level=threat_level,
        )
        with Session(engine) as session:
            session.add(task)
            session.commit()
            session.refresh(task)
        return task

    def list(self, include_old_completed: bool = False) -> list[Task]:
        with Session(engine) as session:
            statement = select(Task)
            if not include_old_completed:
                today = datetime.combine(date.today(), datetime.min.time())
                statement = statement.where(
                    (col(Task.completed_at) == None) | (col(Task.completed_at) >= today)
                )
            return list(session.exec(statement).all())

    def update(
        self,
        task_id: str,
        title: str | None = None,
        status: str | None = None,
        description: str | None = None,
        due_date: date | None = None,
        deadline_type: str | None = None,
        defer_until: date | None = None,
        energy: str | None = None,
        recurrence: int | None = None,
        next_user_review: date | None = None,
        user_review_notes: str | None = None,
        next_ai_review: date | None = None,
        ai_review_notes: str | None = None,
        notes: str | None = None,
        size: int | None = None,
        quest_id: str | None = None,
        threat_level: str | None = None,
        context_tags: list[str] | None = None,
    ) -> Task | None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return None
            if title is not None:
                task.title = title
            if status is not None:
                task.status = status
                if status in ("done", "evaluated"):
                    if task.completed_at is None:
                        task.completed_at = datetime.now()
                else:
                    task.completed_at = None
            if description is not None:
                task.description = description
            if due_date is not None:
                task.due_date = due_date
            if deadline_type is not None:
                task.deadline_type = deadline_type
            if defer_until is not None:
                task.defer_until = defer_until
            if energy is not None:
                task.energy = energy
            if recurrence is not None:
                task.recurrence = recurrence
            if next_user_review is not None:
                task.next_user_review = next_user_review
            if user_review_notes is not None:
                task.user_review_notes = user_review_notes
            if next_ai_review is not None:
                task.next_ai_review = next_ai_review
            if ai_review_notes is not None:
                task.ai_review_notes = ai_review_notes
            if notes is not None:
                task.notes = notes
            if size is not None:
                task.size = size
            if quest_id is not None:
                task.quest_id = quest_id
            if threat_level is not None:
                task.threat_level = threat_level
            if context_tags is not None:
                task.context_tags = context_tags
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    def mark_reviewed(self, task_id: str) -> Task | None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return None
            task.next_user_review = date.today() + timedelta(days=7)
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    def flag_for_review(self, task_id: str) -> Task | None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return None
            task.next_user_review = date.today()
            session.add(task)
            session.commit()
            session.refresh(task)
            return task
