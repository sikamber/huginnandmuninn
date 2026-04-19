from datetime import date, datetime
from uuid import uuid4

from sqlmodel import Field, Session, SQLModel, col, select

from database import engine


class QuestLine(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    title: str
    description: str | None = None
    status: str = "available"
    due_date: date | None = None
    deadline_type: str | None = None
    deadline_note: str | None = None
    defer_until: date | None = None
    energy: str | None = None
    recurrence: int | None = None
    last_reviewed: date | None = None
    review_interval: int | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class Quest(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    title: str
    description: str | None = None
    status: str = "available"
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
    quest_line_id: str | None = Field(default=None, foreign_key="questline.id")
    created_at: datetime = Field(default_factory=datetime.now)


class QuestLineStore:
    def create(self, title: str, description: str | None = None, status: str = "available") -> QuestLine:
        quest_line = QuestLine(title=title, description=description, status=status)
        with Session(engine) as session:
            session.add(quest_line)
            session.commit()
            session.refresh(quest_line)
        return quest_line

    def list(self, include_done: bool = False) -> list[QuestLine]:
        with Session(engine) as session:
            statement = select(QuestLine)
            if not include_done:
                statement = statement.where(col(QuestLine.status) != "done")
            return list(session.exec(statement).all())

    def update(
        self,
        quest_line_id: str,
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
    ) -> QuestLine | None:
        with Session(engine) as session:
            quest_line = session.get(QuestLine, quest_line_id)
            if not quest_line:
                return None
            if title is not None:
                quest_line.title = title
            if status is not None:
                quest_line.status = status
            if description is not None:
                quest_line.description = description
            if due_date is not None:
                quest_line.due_date = due_date
            if deadline_type is not None:
                quest_line.deadline_type = deadline_type
            if deadline_note is not None:
                quest_line.deadline_note = deadline_note
            if defer_until is not None:
                quest_line.defer_until = defer_until
            if energy is not None:
                quest_line.energy = energy
            if recurrence is not None:
                quest_line.recurrence = recurrence
            if review_interval is not None:
                quest_line.review_interval = review_interval
            if notes is not None:
                quest_line.notes = notes
            session.add(quest_line)
            session.commit()
            session.refresh(quest_line)
            return quest_line

    def mark_reviewed(self, quest_line_id: str) -> QuestLine | None:
        with Session(engine) as session:
            quest_line = session.get(QuestLine, quest_line_id)
            if not quest_line:
                return None
            quest_line.last_reviewed = date.today()
            session.add(quest_line)
            session.commit()
            session.refresh(quest_line)
            return quest_line

    def flag_for_review(self, quest_line_id: str) -> QuestLine | None:
        with Session(engine) as session:
            quest_line = session.get(QuestLine, quest_line_id)
            if not quest_line:
                return None
            quest_line.last_reviewed = None
            if not quest_line.review_interval:
                quest_line.review_interval = 1
            session.add(quest_line)
            session.commit()
            session.refresh(quest_line)
            return quest_line


class QuestStore:
    def create(
        self,
        title: str,
        description: str | None = None,
        status: str = "available",
        quest_line_id: str | None = None,
        size: int | None = None,
    ) -> Quest:
        quest = Quest(title=title, description=description, status=status, quest_line_id=quest_line_id, size=size)
        with Session(engine) as session:
            session.add(quest)
            session.commit()
            session.refresh(quest)
        return quest

    def list(self, include_done: bool = False, quest_line_id: str | None = None) -> list[Quest]:
        with Session(engine) as session:
            statement = select(Quest)
            if not include_done:
                statement = statement.where(col(Quest.status) != "done")
            if quest_line_id:
                statement = statement.where(col(Quest.quest_line_id) == quest_line_id)
            return list(session.exec(statement).all())

    def update(
        self,
        quest_id: str,
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
        quest_line_id: str | None = None,
        size: int | None = None,
    ) -> Quest | None:
        with Session(engine) as session:
            quest = session.get(Quest, quest_id)
            if not quest:
                return None
            if title is not None:
                quest.title = title
            if status is not None:
                quest.status = status
            if description is not None:
                quest.description = description
            if due_date is not None:
                quest.due_date = due_date
            if deadline_type is not None:
                quest.deadline_type = deadline_type
            if deadline_note is not None:
                quest.deadline_note = deadline_note
            if defer_until is not None:
                quest.defer_until = defer_until
            if energy is not None:
                quest.energy = energy
            if recurrence is not None:
                quest.recurrence = recurrence
            if review_interval is not None:
                quest.review_interval = review_interval
            if notes is not None:
                quest.notes = notes
            if quest_line_id is not None:
                quest.quest_line_id = quest_line_id
            if size is not None:
                quest.size = size
            session.add(quest)
            session.commit()
            session.refresh(quest)
            return quest

    def mark_reviewed(self, quest_id: str) -> Quest | None:
        with Session(engine) as session:
            quest = session.get(Quest, quest_id)
            if not quest:
                return None
            quest.last_reviewed = date.today()
            session.add(quest)
            session.commit()
            session.refresh(quest)
            return quest

    def flag_for_review(self, quest_id: str) -> Quest | None:
        with Session(engine) as session:
            quest = session.get(Quest, quest_id)
            if not quest:
                return None
            quest.last_reviewed = None
            if not quest.review_interval:
                quest.review_interval = 1
            session.add(quest)
            session.commit()
            session.refresh(quest)
            return quest
