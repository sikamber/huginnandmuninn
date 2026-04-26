from datetime import date, timedelta

from sqlmodel import Session, col, select

from database import engine
from inbox import InboxItem
from quests import Quest, QuestLine
from subjects import Subject
from tasks import Task

_ACTIVE_TASK = (col(Task.status) != "done") & (col(Task.status) != "evaluated")
_ACTIVE_QUEST = col(Quest.status) != "done"
_ACTIVE_QL = col(QuestLine.status) != "done"


def get_critical_items(today: date | None = None) -> list[dict]:
    """Returns items needing immediate attention with a reason for each."""
    if today is None:
        today = date.today()

    with Session(engine) as session:
        tasks = list(session.exec(select(Task).where(_ACTIVE_TASK)).all())
        quests = list(session.exec(select(Quest).where(_ACTIVE_QUEST)).all())
        quest_lines = list(session.exec(select(QuestLine).where(_ACTIVE_QL)).all())
        done_quests = list(session.exec(select(Quest).where(col(Quest.status) == "done")).all())
        done_quest_lines = list(session.exec(select(QuestLine).where(col(QuestLine.status) == "done")).all())
        urgent_inbox = list(session.exec(
            select(InboxItem).where(col(InboxItem.status) == "unprocessed")
        ).all())

    done_quest_ids = {q.id for q in done_quests}
    done_ql_ids = {ql.id for ql in done_quest_lines}
    quest_by_id = {q.id: q for q in quests + done_quests}

    critical = []
    seen_ids = set()

    def _add(item_id, title, reason):
        if item_id not in seen_ids:
            seen_ids.add(item_id)
            critical.append({"id": item_id, "title": title, "reason": reason})

    # Overdue hard deadlines
    for item in tasks + quests + quest_lines:
        if item.due_date and item.deadline_type == "hard" and item.due_date < today:
            _add(item.id, item.title, f"hard deadline missed ({item.due_date})")

    # Upcoming hard deadlines (within 7 days)
    for item in tasks + quests + quest_lines:
        if item.due_date and item.deadline_type == "hard" and today <= item.due_date <= today + timedelta(days=7):
            _add(item.id, item.title, f"hard deadline in {(item.due_date - today).days}d ({item.due_date})")

    # Upcoming soft deadlines (within 14 days)
    for item in tasks + quests + quest_lines:
        if item.due_date and item.deadline_type == "soft" and item.due_date <= today + timedelta(days=14):
            _add(item.id, item.title, f"soft deadline in {(item.due_date - today).days}d ({item.due_date})")

    # Tasks belonging to done quests
    for task in tasks:
        if task.quest_id and task.quest_id in done_quest_ids:
            _add(task.id, task.title, "belongs to completed quest")

    # Quests belonging to done quest lines
    for quest in quests:
        if quest.quest_line_id and quest.quest_line_id in done_ql_ids:
            _add(quest.id, quest.title, "belongs to completed quest line")

    # Urgent inbox items
    for item in urgent_inbox:
        if item.content.startswith("!!"):
            _add(item.id, item.content[:60], "urgent inbox item")

    # High-threat tasks whose quest isn't tracked (or no quest)
    for task in tasks:
        if task.threat_level == "high":
            quest = quest_by_id.get(task.quest_id) if task.quest_id else None
            if quest is None or quest.status != "tracked":
                reason = "high-threat, quest not tracked" if quest else "high-threat, no parent quest"
                _add(task.id, task.title, reason)

    return critical


def count_review_items(today: date | None = None) -> int:
    """Count items currently due for user review."""
    if today is None:
        today = date.today()

    with Session(engine) as session:
        tasks = list(session.exec(select(Task).where(_ACTIVE_TASK)).all())
        quests = list(session.exec(select(Quest).where(_ACTIVE_QUEST)).all())
        quest_lines = list(session.exec(select(QuestLine).where(_ACTIVE_QL)).all())

    return sum(
        1 for item in tasks + quests + quest_lines
        if item.next_user_review and item.next_user_review <= today
    )


def get_next_review_item(today: date | None = None) -> dict | None:
    if today is None:
        today = date.today()

    candidates = []

    with Session(engine) as session:
        tasks = list(session.exec(select(Task).where(_ACTIVE_TASK)).all())
        quests = list(session.exec(select(Quest).where(_ACTIVE_QUEST)).all())
        quest_lines = list(session.exec(select(QuestLine).where(_ACTIVE_QL)).all())

    for item_type, item in (
        [("task", t) for t in tasks]
        + [("quest", q) for q in quests]
        + [("quest_line", ql) for ql in quest_lines]
    ):
        if item.next_user_review and item.next_user_review <= today:
            days_overdue = (today - item.next_user_review).days
            candidates.append((days_overdue, item_type, item))

    if not candidates:
        return None

    candidates.sort(key=lambda x: -x[0])
    days_overdue, item_type, item = candidates[0]

    result = {
        "type": item_type,
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "notes": item.notes,
        "user_review_notes": item.user_review_notes,
        "status": item.status,
        "next_user_review": str(item.next_user_review),
        "days_overdue": days_overdue,
    }

    if item_type == "quest":
        result["tasks"] = [
            {"id": t.id, "title": t.title, "status": t.status, "description": t.description}
            for t in tasks if t.quest_id == item.id
        ]
    elif item_type == "quest_line":
        result["quests"] = [
            {"id": q.id, "title": q.title, "status": q.status, "description": q.description}
            for q in quests if q.quest_line_id == item.id
        ]

    return result


def get_ai_review_items(today: date | None = None) -> dict:
    """Returns items needing AI review: completed tasks and items with next_ai_review due."""
    if today is None:
        today = date.today()

    with Session(engine) as session:
        done_tasks = list(session.exec(
            select(Task).where(col(Task.status) == "done")
        ).all())
        ai_tasks = list(session.exec(
            select(Task).where(
                col(Task.next_ai_review) != None,
                col(Task.next_ai_review) <= today,
                _ACTIVE_TASK,
            )
        ).all())
        ai_quests = list(session.exec(
            select(Quest).where(
                col(Quest.next_ai_review) != None,
                col(Quest.next_ai_review) <= today,
                _ACTIVE_QUEST,
            )
        ).all())
        ai_qls = list(session.exec(
            select(QuestLine).where(
                col(QuestLine.next_ai_review) != None,
                col(QuestLine.next_ai_review) <= today,
                _ACTIVE_QL,
            )
        ).all())

    return {
        "done_tasks": [
            {"id": t.id, "title": t.title, "description": t.description, "notes": t.notes}
            for t in done_tasks
        ],
        "ai_review_items": (
            [{"type": "task", "id": t.id, "title": t.title, "ai_review_notes": t.ai_review_notes} for t in ai_tasks]
            + [{"type": "quest", "id": q.id, "title": q.title, "ai_review_notes": q.ai_review_notes} for q in ai_quests]
            + [{"type": "quest_line", "id": ql.id, "title": ql.title, "ai_review_notes": ql.ai_review_notes} for ql in ai_qls]
        ),
    }


def get_no_oversight_items(today: date | None = None) -> list[dict]:
    if today is None:
        today = date.today()

    with Session(engine) as session:
        tasks = list(session.exec(select(Task).where(_ACTIVE_TASK)).all())
        quests = list(session.exec(select(Quest).where(_ACTIVE_QUEST)).all())
        quest_lines = list(session.exec(select(QuestLine).where(_ACTIVE_QL)).all())

    result = []
    for item_type, item in (
        [("task", t) for t in tasks]
        + [("quest", q) for q in quests]
        + [("quest_line", ql) for ql in quest_lines]
    ):
        has_oversight = (
            (item_type == "task" and (item.quest_id or item.next_user_review or item.next_ai_review))
            or (item_type == "quest" and (item.quest_line_id or item.next_user_review or item.next_ai_review))
            or (item_type == "quest_line" and (item.next_user_review or item.next_ai_review))
        )
        if not has_oversight:
            if item_type == "task" and (today - item.created_at.date()).days < 7:
                continue
            result.append({"type": item_type, "id": item.id, "title": item.title})
    return result


def get_empty_structure_items() -> dict:
    with Session(engine) as session:
        tasks = list(session.exec(select(Task).where(_ACTIVE_TASK)).all())
        quests = list(session.exec(select(Quest).where(_ACTIVE_QUEST)).all())
        quest_lines = list(session.exec(select(QuestLine).where(_ACTIVE_QL)).all())

    task_count_by_quest: dict[str, int] = {}
    for task in tasks:
        if task.quest_id:
            task_count_by_quest[task.quest_id] = task_count_by_quest.get(task.quest_id, 0) + 1

    quest_count_by_line: dict[str, int] = {}
    for quest in quests:
        if quest.quest_line_id:
            quest_count_by_line[quest.quest_line_id] = quest_count_by_line.get(quest.quest_line_id, 0) + 1

    return {
        "quests_no_tasks": [
            {"id": q.id, "title": q.title, "status": q.status}
            for q in quests if task_count_by_quest.get(q.id, 0) == 0
        ],
        "quest_lines_no_quests": [
            {"id": ql.id, "title": ql.title, "status": ql.status}
            for ql in quest_lines if quest_count_by_line.get(ql.id, 0) == 0
        ],
    }


def build_review_summary(inbox_store, subject_store, energy_level: str | None = None) -> str:
    today = date.today()

    critical = get_critical_items(today)
    all_inbox = inbox_store.list_unprocessed()
    noncritical_inbox = [i for i in all_inbox if not i.content.startswith("!!")]
    review_count = count_review_items(today)
    open_subjects = subject_store.list(state="open")

    parts = []

    if critical:
        lines = "\n".join(f"- {item['title']} — {item['reason']}" for item in critical)
        parts.append(f"**{len(critical)} critical item(s):**\n{lines}")

    counts = []
    if noncritical_inbox:
        counts.append(f"**{len(noncritical_inbox)} inbox item(s)** to process")
    if review_count:
        counts.append(f"**{review_count} item(s)** due for review")
    if counts:
        parts.append("\n".join(counts))

    if open_subjects:
        subject_lines = "\n".join(
            f"- **{s.title}**" + (f" — {s.summary}" if s.summary else "")
            for s in open_subjects
        )
        parts.append(f"**Open subjects:**\n{subject_lines}")

    if not parts:
        return "Everything looks clear — no critical items, no inbox, nothing due for review."

    return "\n\n".join(parts)
