from datetime import date, datetime, timedelta
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
    defer_until: date | None = None
    energy: str | None = None
    recurrence: int | None = None
    next_user_review: date | None = None
    user_review_notes: str | None = None
    next_ai_review: date | None = None
    ai_review_notes: str | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class Quest(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    title: str
    description: str | None = None
    status: str = "available"
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
        defer_until: date | None = None,
        energy: str | None = None,
        recurrence: int | None = None,
        next_user_review: date | None = None,
        user_review_notes: str | None = None,
        next_ai_review: date | None = None,
        ai_review_notes: str | None = None,
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
            if defer_until is not None:
                quest_line.defer_until = defer_until
            if energy is not None:
                quest_line.energy = energy
            if recurrence is not None:
                quest_line.recurrence = recurrence
            if next_user_review is not None:
                quest_line.next_user_review = next_user_review
            if user_review_notes is not None:
                quest_line.user_review_notes = user_review_notes
            if next_ai_review is not None:
                quest_line.next_ai_review = next_ai_review
            if ai_review_notes is not None:
                quest_line.ai_review_notes = ai_review_notes
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
            quest_line.next_user_review = date.today() + timedelta(days=7)
            session.add(quest_line)
            session.commit()
            session.refresh(quest_line)
            return quest_line

    def flag_for_review(self, quest_line_id: str) -> QuestLine | None:
        with Session(engine) as session:
            quest_line = session.get(QuestLine, quest_line_id)
            if not quest_line:
                return None
            quest_line.next_user_review = date.today()
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
        defer_until: date | None = None,
        energy: str | None = None,
        recurrence: int | None = None,
        next_user_review: date | None = None,
        user_review_notes: str | None = None,
        next_ai_review: date | None = None,
        ai_review_notes: str | None = None,
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
            if defer_until is not None:
                quest.defer_until = defer_until
            if energy is not None:
                quest.energy = energy
            if recurrence is not None:
                quest.recurrence = recurrence
            if next_user_review is not None:
                quest.next_user_review = next_user_review
            if user_review_notes is not None:
                quest.user_review_notes = user_review_notes
            if next_ai_review is not None:
                quest.next_ai_review = next_ai_review
            if ai_review_notes is not None:
                quest.ai_review_notes = ai_review_notes
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
            quest.next_user_review = date.today() + timedelta(days=7)
            session.add(quest)
            session.commit()
            session.refresh(quest)
            return quest

    def flag_for_review(self, quest_id: str) -> Quest | None:
        with Session(engine) as session:
            quest = session.get(Quest, quest_id)
            if not quest:
                return None
            quest.next_user_review = date.today()
            session.add(quest)
            session.commit()
            session.refresh(quest)
            return quest
