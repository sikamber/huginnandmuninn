from datetime import datetime
from uuid import uuid4

from sqlmodel import Field, Session, SQLModel, col, select

from database import engine

_THREAT_ORDER = {"high": 0, "medium": 1, "low": 2}


class InboxItem(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    content: str
    status: str = "unprocessed"
    energy: str | None = None
    threat_level: str = "medium"
    created_at: datetime = Field(default_factory=datetime.now)


class InboxStore:
    def create(self, content: str, threat_level: str | None = None) -> InboxItem:
        if threat_level is None:
            threat_level = "high" if content.startswith("!") else "medium"
        item = InboxItem(content=content, threat_level=threat_level)
        with Session(engine) as session:
            session.add(item)
            session.commit()
            session.refresh(item)
        return item

    def list_unprocessed(self) -> list[InboxItem]:
        with Session(engine) as session:
            items = list(session.exec(
                select(InboxItem).where(col(InboxItem.status) == "unprocessed").order_by(col(InboxItem.created_at))
            ).all())
        items.sort(key=lambda i: (_THREAT_ORDER.get(i.threat_level, 1), i.created_at))
        return items

    def get_next(self, max_energy: str | None = None) -> InboxItem | None:
        energy_order = {"low": 0, "medium": 1, "high": 2}
        with Session(engine) as session:
            statement = select(InboxItem).where(col(InboxItem.status) == "unprocessed")
            if max_energy:
                max_level = energy_order.get(max_energy, 2)
                allowed = [e for e, level in energy_order.items() if level <= max_level]
                statement = statement.where(
                    (col(InboxItem.energy) == None) | col(InboxItem.energy).in_(allowed)
                )
            statement = statement.order_by(col(InboxItem.created_at))
            items = list(session.exec(statement).all())

        if not items:
            return None
        items.sort(key=lambda i: (_THREAT_ORDER.get(i.threat_level, 1), i.created_at))
        return items[0]

    VALID_STATUSES = {"unprocessed", "processed", "discarded"}

    def update(
        self,
        item_id: str,
        status: str | None = None,
        energy: str | None = None,
        threat_level: str | None = None,
    ) -> InboxItem | None:
        with Session(engine) as session:
            item = session.get(InboxItem, item_id)
            if not item:
                return None
            if status is not None:
                if status not in self.VALID_STATUSES:
                    raise ValueError(f"Invalid inbox status '{status}'. Must be one of: {self.VALID_STATUSES}")
                item.status = status
            if energy is not None:
                item.energy = energy
            if threat_level is not None:
                item.threat_level = threat_level
            session.add(item)
            session.commit()
            session.refresh(item)
            return item
