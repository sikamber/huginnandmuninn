from datetime import date, datetime
from uuid import uuid4

from sqlmodel import Field, Session, SQLModel, col, select

from database import engine


class Task(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    title: str
    description: str | None = None
    status: str = "todo"
    due_date: date | None = None
    deadline_type: str | None = None
    deadline_note: str | None = None
    defer_until: date | None = None
    energy: str | None = None
    recurrence: int | None = None
    last_reviewed: date | None = None
    review_interval: int | None = None
    notes: str | None = None
    size: int | None = None
    quest_id: str | None = Field(default=None, foreign_key="quest.id")
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None


class TaskStore:
    def create(
        self,
        title: str,
        description: str | None = None,
        due_date: date | None = None,
        quest_id: str | None = None,
        deadline_type: str | None = None,
        deadline_note: str | None = None,
        defer_until: date | None = None,
        energy: str | None = None,
        recurrence: int | None = None,
        review_interval: int | None = None,
        size: int | None = None,
    ) -> Task:
        task = Task(
            title=title,
            description=description,
            due_date=due_date,
            quest_id=quest_id,
            deadline_type=deadline_type,
            deadline_note=deadline_note,
            defer_until=defer_until,
            energy=energy,
            recurrence=recurrence,
            review_interval=review_interval,
            size=size,
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
        deadline_note: str | None = None,
        defer_until: date | None = None,
        energy: str | None = None,
        recurrence: int | None = None,
        review_interval: int | None = None,
        notes: str | None = None,
        size: int | None = None,
        quest_id: str | None = None,
    ) -> Task | None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return None
            if title is not None:
                task.title = title
            if status is not None:
                task.status = status
                task.completed_at = datetime.now() if status == "done" else None
            if description is not None:
                task.description = description
            if due_date is not None:
                task.due_date = due_date
            if deadline_type is not None:
                task.deadline_type = deadline_type
            if deadline_note is not None:
                task.deadline_note = deadline_note
            if defer_until is not None:
                task.defer_until = defer_until
            if energy is not None:
                task.energy = energy
            if recurrence is not None:
                task.recurrence = recurrence
            if review_interval is not None:
                task.review_interval = review_interval
            if notes is not None:
                task.notes = notes
            if size is not None:
                task.size = size
            if quest_id is not None:
                task.quest_id = quest_id
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    def mark_reviewed(self, task_id: str) -> Task | None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return None
            task.last_reviewed = date.today()
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    def flag_for_review(self, task_id: str) -> Task | None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return None
            task.last_reviewed = None
            if not task.review_interval:
                task.review_interval = 1
            session.add(task)
            session.commit()
            session.refresh(task)
            return task
