from datetime import date, timedelta

from sqlmodel import Session, col, select

from database import engine
from inbox import InboxItem
from quests import Quest, QuestLine
from tasks import Task

# --- Deterministic inbox rules ---
# Predicate signature: (item, today) -> bool
INBOX_RULES: list[tuple[str, callable]] = [
    (
        "urgent",
        lambda item, today: item.content.startswith("!!"),
    ),
    (
        "stale_unclassified",
        lambda item, today: (
            item.energy is None and (today - item.created_at.date()).days > 1
        ),
    ),
]

# --- Deterministic quest rules ---
# Predicate signature: (quest, task_count) -> bool
QUEST_RULES: list[tuple[str, callable]] = [
    (
        "no_tasks",
        lambda quest, task_count: task_count == 0,
    ),
]

# --- Deterministic quest line rules ---
# Predicate signature: (quest_line, quest_count) -> bool
QUEST_LINE_RULES: list[tuple[str, callable]] = [
    (
        "no_quests",
        lambda ql, quest_count: quest_count == 0,
    ),
]

# --- Parent-aware rules (checked against done parents) ---
# Predicate signature: (task, done_quest_ids: set) -> bool
TASK_PARENT_RULES: list[tuple[str, callable]] = [
    (
        "quest_done",
        lambda task, done_quest_ids: (
            task.quest_id is not None and task.quest_id in done_quest_ids
        ),
    ),
]

# Predicate signature: (quest, done_ql_ids: set) -> bool
QUEST_PARENT_RULES: list[tuple[str, callable]] = [
    (
        "quest_line_done",
        lambda quest, done_ql_ids: (
            quest.quest_line_id is not None and quest.quest_line_id in done_ql_ids
        ),
    ),
]


def get_radar(today: date | None = None) -> dict:
    if today is None:
        today = date.today()

    hard_overdue = []
    hard_upcoming = []
    soft_upcoming = []
    inbox_flags: dict[str, list] = {label: [] for label, _ in INBOX_RULES}
    task_parent_flags: dict[str, list] = {label: [] for label, _ in TASK_PARENT_RULES}
    quest_parent_flags: dict[str, list] = {label: [] for label, _ in QUEST_PARENT_RULES}

    with Session(engine) as session:
        tasks = list(session.exec(select(Task).where(col(Task.status) != "done")).all())
        quests = list(
            session.exec(select(Quest).where(col(Quest.status) != "done")).all()
        )
        quest_lines = list(
            session.exec(select(QuestLine).where(col(QuestLine.status) != "done")).all()
        )
        done_quests = list(
            session.exec(select(Quest).where(col(Quest.status) == "done")).all()
        )
        done_quest_lines = list(
            session.exec(select(QuestLine).where(col(QuestLine.status) == "done")).all()
        )
        inbox_items = list(
            session.exec(
                select(InboxItem).where(col(InboxItem.status) == "unprocessed")
            ).all()
        )

    done_quest_ids = {q.id for q in done_quests}
    done_ql_ids = {ql.id for ql in done_quest_lines}

    for task in tasks:
        entry = {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "quest_id": task.quest_id,
        }
        for label, predicate in TASK_PARENT_RULES:
            if predicate(task, done_quest_ids):
                task_parent_flags[label].append(entry)

    for quest in quests:
        entry = {
            "id": quest.id,
            "title": quest.title,
            "status": quest.status,
            "quest_line_id": quest.quest_line_id,
        }
        for label, predicate in QUEST_PARENT_RULES:
            if predicate(quest, done_ql_ids):
                quest_parent_flags[label].append(entry)

    for item in inbox_items:
        entry = {
            "id": item.id,
            "content": item.content,
            "created_at": str(item.created_at.date()),
            "energy": item.energy,
        }
        for label, predicate in INBOX_RULES:
            if predicate(item, today):
                inbox_flags[label].append(entry)

    all_items = (
        [("task", t) for t in tasks]
        + [("quest", q) for q in quests]
        + [("quest_line", ql) for ql in quest_lines]
    )

    for item_type, item in all_items:
        entry = {"type": item_type, "id": item.id, "title": item.title}

        if item.due_date:
            if item.deadline_type == "hard":
                if item.due_date < today:
                    hard_overdue.append(
                        {
                            **entry,
                            "due_date": str(item.due_date),
                            "note": item.deadline_note,
                        }
                    )
                elif item.due_date <= today + timedelta(days=7):
                    hard_upcoming.append(
                        {
                            **entry,
                            "due_date": str(item.due_date),
                            "note": item.deadline_note,
                        }
                    )
            elif item.deadline_type == "soft":
                if item.due_date <= today + timedelta(days=14):
                    soft_upcoming.append(
                        {
                            **entry,
                            "due_date": str(item.due_date),
                            "note": item.deadline_note,
                        }
                    )

    return {
        "hard_overdue": hard_overdue,
        "hard_upcoming": hard_upcoming,
        "soft_upcoming": soft_upcoming,
        "inbox_flags": inbox_flags,
        "task_parent_flags": task_parent_flags,
        "quest_parent_flags": quest_parent_flags,
    }



