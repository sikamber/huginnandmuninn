from datetime import datetime
from uuid import uuid4

from sqlmodel import Field, Session, SQLModel, col, select

from database import engine


class Subject(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    title: str
    state: str = "open"
    summary: str | None = None
    contents: str
    last_discussed: datetime = Field(default_factory=datetime.now)
    created_at: datetime = Field(default_factory=datetime.now)


class SubjectStore:
    def create(self, title: str, contents: str, summary: str | None = None, state: str = "open") -> Subject:
        subject = Subject(title=title, contents=contents, summary=summary, state=state)
        with Session(engine) as session:
            session.add(subject)
            session.commit()
            session.refresh(subject)
        return subject

    def list(self, state: str | None = None) -> list[Subject]:
        with Session(engine) as session:
            statement = select(Subject)
            if state:
                statement = statement.where(col(Subject.state) == state)
            return list(session.exec(statement).all())

    def get(self, subject_id: str) -> Subject | None:
        with Session(engine) as session:
            return session.get(Subject, subject_id)

    def update(self, subject_id: str, title: str | None = None, contents: str | None = None, summary: str | None = None, state: str | None = None) -> Subject | None:
        with Session(engine) as session:
            subject = session.get(Subject, subject_id)
            if not subject:
                return None
            if title is not None:
                subject.title = title
            if contents is not None:
                subject.contents = contents
            if summary is not None:
                subject.summary = summary
            if state is not None:
                subject.state = state
            subject.last_discussed = datetime.now()
            session.add(subject)
            session.commit()
            session.refresh(subject)
        return subject
