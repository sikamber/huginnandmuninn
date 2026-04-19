from datetime import date

from sqlmodel import Session, col, select

from database import engine
from quests import Quest, QuestLine
from tasks import Task

NO_OVERSIGHT_RULES: list[tuple[str, callable]] = [
    ("task", lambda t: t.quest_id is None and t.review_interval is None),
    ("quest", lambda q: q.quest_line_id is None and q.review_interval is None),
    ("quest_line", lambda ql: ql.review_interval is None),
]


def get_next_review_item(today: date | None = None) -> dict | None:
    if today is None:
        today = date.today()

    candidates = []

    with Session(engine) as session:
        tasks = list(session.exec(select(Task).where(col(Task.status) != "done")).all())
        quests = list(session.exec(select(Quest).where(col(Quest.status) != "done")).all())
        quest_lines = list(session.exec(select(QuestLine).where(col(QuestLine.status) != "done")).all())

    for item_type, item in (
        [("task", t) for t in tasks]
        + [("quest", q) for q in quests]
        + [("quest_line", ql) for ql in quest_lines]
    ):
        if item.review_interval:
            baseline = item.last_reviewed if item.last_reviewed else item.created_at.date()
            days_overdue = (today - baseline).days - item.review_interval
        elif item_type == "task" and item.last_reviewed is None:
            days_overdue = (today - item.created_at.date()).days - 7
        else:
            continue
        if days_overdue >= 0:
            candidates.append((days_overdue, item_type, item))

    if not candidates:
        return None

    candidates.sort(key=lambda x: -x[0])
    days_overdue, item_type, item = candidates[0]

    return {
        "type": item_type,
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "notes": item.notes,
        "status": item.status,
        "last_reviewed": str(item.last_reviewed) if item.last_reviewed else "never",
        "days_overdue": days_overdue,
    }


def get_no_oversight_items(today: date | None = None) -> list[dict]:
    if today is None:
        today = date.today()
    oversight_predicates = {label: pred for label, pred in NO_OVERSIGHT_RULES}
    with Session(engine) as session:
        tasks = list(session.exec(select(Task).where(col(Task.status) != "done")).all())
        quests = list(session.exec(select(Quest).where(col(Quest.status) != "done")).all())
        quest_lines = list(session.exec(select(QuestLine).where(col(QuestLine.status) != "done")).all())
    result = []
    for item_type, item in (
        [("task", t) for t in tasks]
        + [("quest", q) for q in quests]
        + [("quest_line", ql) for ql in quest_lines]
    ):
        pred = oversight_predicates.get(item_type)
        if pred and pred(item):
            if item_type == "task" and (today - item.created_at.date()).days < 7:
                continue
            result.append({"type": item_type, "id": item.id, "title": item.title})
    return result


def get_empty_structure_items() -> dict:
    with Session(engine) as session:
        tasks = list(session.exec(select(Task).where(col(Task.status) != "done")).all())
        quests = list(session.exec(select(Quest).where(col(Quest.status) != "done")).all())
        quest_lines = list(session.exec(select(QuestLine).where(col(QuestLine.status) != "done")).all())

    task_count_by_quest: dict[str, int] = {}
    for task in tasks:
        if task.quest_id:
            task_count_by_quest[task.quest_id] = task_count_by_quest.get(task.quest_id, 0) + 1

    quest_count_by_line: dict[str, int] = {}
    for quest in quests:
        if quest.quest_line_id:
            quest_count_by_line[quest.quest_line_id] = quest_count_by_line.get(quest.quest_line_id, 0) + 1

    quests_no_tasks = [
        {"id": q.id, "title": q.title, "status": q.status}
        for q in quests if task_count_by_quest.get(q.id, 0) == 0
    ]
    quest_lines_no_quests = [
        {"id": ql.id, "title": ql.title, "status": ql.status}
        for ql in quest_lines if quest_count_by_line.get(ql.id, 0) == 0
    ]
    return {"quests_no_tasks": quests_no_tasks, "quest_lines_no_quests": quest_lines_no_quests}
