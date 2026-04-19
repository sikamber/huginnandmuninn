from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
import json
import logging
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("huginn")

from fastapi import FastAPI
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.anthropic import AnthropicModelSettings

CACHE_SETTINGS = AnthropicModelSettings(
    anthropic_cache_tool_definitions="1h",
    anthropic_cache_instructions="1h",
)

from cache import response_cache
from database import create_tables
from deps import AppDeps
from inbox import InboxItem, InboxStore
from quests import Quest, QuestLine, QuestLineStore, QuestStore
from radar import get_radar
from review import get_empty_structure_items, get_no_oversight_items, get_next_review_item
from subjects import Subject, SubjectStore
from tasks import Task, TaskStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(lifespan=lifespan)
deps = AppDeps(
    tasks=TaskStore(),
    subjects=SubjectStore(),
    quests=QuestStore(),
    quest_lines=QuestLineStore(),
    inbox=InboxStore(),
)
agent = Agent("anthropic:claude-sonnet-4-6", deps_type=AppDeps)

RADAR_CLEAR = "Your radar is clear — nothing is overdue, flagged, or due for review right now."
REVIEW_CLEAR = "Nothing to review right now — no overdue reviews, unprocessed inbox items, or open subjects."

ENERGY_ORDER = {"low": 0, "medium": 1, "high": 2}

def _within_energy(item_energy: str | None, max_energy: str | None) -> bool:
    if max_energy is None or item_energy is None:
        return True
    return ENERGY_ORDER.get(item_energy, 0) <= ENERGY_ORDER.get(max_energy, 2)

def _empty_message(mode: str, hidden: int, energy_level: str | None) -> str:
    suffix = f" ({hidden} item(s) hidden above your current energy level.)" if hidden and energy_level else ""
    if mode == "radar":
        return RADAR_CLEAR
    if mode == "review":
        return REVIEW_CLEAR + suffix
    if mode == "quests":
        base = "No quests match your current energy level." if hidden and energy_level else "No quests yet."
        return base + suffix
    return ""


def build_initial_prompt(mode: str, energy_level: str | None = None) -> tuple[str | None, int]:
    """Returns (prompt_for_ai_or_None, hidden_item_count)."""
    if mode == "radar":
        data = get_radar()
        def _any_items(v) -> bool:
            if isinstance(v, list): return bool(v)
            if isinstance(v, dict): return any(_any_items(x) for x in v.values())
            return bool(v)
        if not any(_any_items(v) for v in data.values()):
            return None, 0
        return (
            "Here is the current radar data. Interpret it and give a concise summary of what needs attention.\n\n"
            f"{json.dumps(data, indent=2)}"
        ), 0

    if mode == "review":
        item = get_next_review_item()
        all_inbox = deps.inbox.list_unprocessed()
        inbox_items = [i for i in all_inbox if _within_energy(i.energy, energy_level)]
        hidden = len(all_inbox) - len(inbox_items)
        open_subjects = deps.subjects.list(state="open")

        parts = []
        if item:
            parts.append("Next item due for review — present it and ask what the user would like to do:\n\n" + json.dumps(item, indent=2))
        if inbox_items:
            first = inbox_items[0]
            first_data = {"kind": "inbox", "id": first.id, "content": first.content, "energy": first.energy, "created_at": str(first.created_at.date())}
            count = len(inbox_items)
            header = f"There are {count} unprocessed inbox item(s). Present the first one, then use get_next_item after each is handled to advance:\n\n"
            parts.append(header + json.dumps(first_data, indent=2))
        if open_subjects:
            subjects_data = [{"id": s.id, "title": s.title, "summary": s.summary, "last_discussed": str(s.last_discussed.date())} for s in open_subjects]
            parts.append("Open subjects (ongoing memory — flag any that seem stale or worth revisiting):\n\n" + json.dumps(subjects_data, indent=2))
        no_oversight = get_no_oversight_items()
        if no_oversight:
            parts.append("Items with no oversight (no parent and no review interval — suggest adding one):\n\n" + json.dumps(no_oversight, indent=2))
        empty_structure = get_empty_structure_items()
        if empty_structure["quests_no_tasks"] or empty_structure["quest_lines_no_quests"]:
            parts.append("Structural gaps (quests with no tasks / quest lines with no quests — worth reviewing):\n\n" + json.dumps(empty_structure, indent=2))
        if hidden:
            parts.append(f"Note: {hidden} inbox item(s) are hidden because they exceed the user's current energy level ({energy_level}).")

        return ("\n\n".join(parts) if parts else None), hidden

    if mode == "quests":
        all_qls = deps.quest_lines.list()
        all_quests = deps.quests.list()

        def _pick_tier(items, *statuses):
            for status in statuses:
                tier = [i for i in items if i.status == status and _within_energy(i.energy, energy_level)]
                if tier:
                    return tier, status
            return [], None

        quest_lines, ql_tier = _pick_tier(all_qls, "tracked", "current", "available")
        quests, q_tier = _pick_tier(all_quests, "tracked", "current", "available")
        active_tier = ql_tier or q_tier

        today = date.today()
        all_energy_filtered = [i for i in all_qls + all_quests if not _within_energy(i.energy, energy_level)]
        all_deferred = [i for i in all_qls + all_quests if i.defer_until and i.defer_until > today]
        hidden = len(all_energy_filtered)
        deferred_count = len(all_deferred)

        if not quest_lines and not quests:
            return None, hidden

        shown_quest_ids = {q.id for q in quests}
        all_tasks = deps.tasks.list()
        relevant_tasks = [
            t for t in all_tasks
            if (t.quest_id in shown_quest_ids or t.quest_id is None)
            and t.status != "done"
            and _within_energy(t.energy, energy_level)
            and not (t.defer_until and t.defer_until > today)
        ]

        # --- Quest page flags ---
        task_count_by_quest = {}
        for t in all_tasks:
            if t.quest_id:
                task_count_by_quest[t.quest_id] = task_count_by_quest.get(t.quest_id, 0) + 1

        flags: dict[str, list] = {}

        # Hard deadlines on shown items
        hard_overdue, hard_upcoming, soft_upcoming = [], [], []
        for item_type, item in (
            [("task", t) for t in relevant_tasks]
            + [("quest", q) for q in quests]
            + [("quest_line", ql) for ql in quest_lines]
        ):
            if not item.due_date:
                continue
            entry = {"type": item_type, "id": item.id, "title": item.title, "due_date": str(item.due_date), "note": item.deadline_note}
            if item.deadline_type == "hard":
                if item.due_date < today:
                    hard_overdue.append(entry)
                elif item.due_date <= today + timedelta(days=7):
                    hard_upcoming.append(entry)
            elif item.deadline_type == "soft" and item.due_date <= today + timedelta(days=14):
                soft_upcoming.append(entry)
        if hard_overdue:
            flags["hard_overdue"] = hard_overdue
        if hard_upcoming:
            flags["hard_upcoming"] = hard_upcoming
        if soft_upcoming:
            flags["soft_upcoming"] = soft_upcoming

        # Tracked/current quests with no tasks
        no_tasks = [
            {"id": q.id, "title": q.title, "status": q.status}
            for q in quests if q.status in ("tracked", "current") and task_count_by_quest.get(q.id, 0) == 0
        ]
        if no_tasks:
            flags["no_tasks"] = no_tasks

        # Newly available (deferred items that just unblocked)
        all_shown = [(t, "task") for t in all_tasks] + [(q, "quest") for q in all_quests] + [(ql, "quest_line") for ql in all_qls]
        newly_available = [
            {"type": itype, "id": i.id, "title": i.title, "deferred_until": str(i.defer_until)}
            for i, itype in all_shown
            if i.defer_until and i.defer_until <= today
        ]
        if newly_available:
            flags["newly_available"] = newly_available

        data: dict = {
            "quest_lines": compact_list(quest_lines),
            "quests": compact_list(quests),
            "tasks": compact_list(relevant_tasks),
        }
        if flags:
            data["flags"] = flags
        prompt = f"Here are the user's {active_tier} quests, quest lines, tasks, and any flags. Skip the overview — go straight to suggesting the most appropriate task(s) to work on next, with brief reasoning. If there are flags, surface any urgent ones concisely before the suggestion.\n\n" + json.dumps(data, indent=2)
        notes = []
        if hidden:
            notes.append(f"{hidden} quest(s)/quest line(s) are hidden because they exceed the user's current energy level ({energy_level}).")
        if deferred_count:
            notes.append(f"{deferred_count} quest(s)/quest line(s) are deferred and not shown.")
        if notes:
            prompt += "\n\nNote: " + " ".join(notes)
        return prompt, hidden

    return None, 0


@agent.system_prompt
def static_prompt() -> str:
    return """You are a personal assistant that helps the user manage their work.

## Structure
- **Task**: a single action. Can stand alone or belong to a Quest. Tasks never belong directly to a Quest Line.
- **Quest**: a multi-step outcome. Can stand alone or belong to a Quest Line.
- **Quest Line**: a long-running project spanning more than a few days. Contains Quests, not Tasks directly.

## Status vocabulary (Quest and Quest Line)
- **tracked**: top priority — surface proactively in every conversation
- **current**: actively being worked on
- **available**: exists but not currently being pursued
- **done**: completed

## Fields
These fields apply to tasks, quests, AND quest lines unless noted:
- `deadline_type`: hard (must happen by due_date) or soft (would like to by due_date)
- `deadline_note`: consequence or fallback if deadline is missed
- `defer_until`: hide from radar until this date
- `energy`: low / medium / high — context needed to engage with this item
- `recurrence`: days between expected recurrences (track via last_reviewed)
- `review_interval`: days between reviews — quest lines support this just like tasks and quests; call mark_reviewed after genuinely reviewing an item
- `notes`: your working memory on an item — observations, hunches, context across conversations

## Behaviour
- Summarise meaningfully — don't just read lists back.
- Do not use emojis or emoticons in any response.
- Call `mark_reviewed` after genuinely reviewing an item, not on passive reads.
- When reviewing items, present one at a time. Do not list everything due for review — use `next_review_item` and present only that item, then wait for the user to respond before moving on.
- For initial overviews, give a high-level summary. When task data is already provided in the prompt, use it directly — do not call list_tasks again. Only call list_tasks when the user explicitly asks for tasks not already in context.
- When creating a quest or quest line, always suggest a status tier (tracked/current/available) based on what the user said, and confirm before creating — do not default to available without saying so.
- When creating a quest that does not belong to a quest line, suggest a review interval (in days) before creating it — standalone quests have no parent to ensure they get revisited.
- Use get_next_item to advance through the review queue. It returns inbox items first, then scheduled review items, then None when everything is clear.
- Verbal acknowledgment is never enough. If the user says "close it", "handled", "discard", "skip", "move on", or similar about an inbox item, you MUST call update_inbox_item before saying anything else. No exceptions.
- After handling any item (inbox or review), immediately call get_next_item — do not ask what to do next, do not pause, just fetch and present it.
- When the user gives instructions for an inbox item, check if anything critical is missing. If not, execute immediately: create the task/quest/note, call update_inbox_item, call get_next_item, present the result — no summary, no confirmation prompt, no question about what to do next.
- When the user says goodbye, review what was discussed and create or update subjects to capture anything worth remembering. Ask if unsure.

## Radar rules (soft guidance)
In addition to the structured radar data, apply these when reviewing or giving a radar check:
- Flag any quest line that has no quests with status 'current' or 'tracked' — it may be stalled.
- Flag any quest marked 'tracked' that has no tasks.
- Suggest archiving (marking done) quests or quest lines that haven't been touched in a long time with no upcoming deadlines."""


@agent.system_prompt
def dynamic_prompt(ctx: RunContext[AppDeps]) -> str:
    now = datetime.now(ZoneInfo("Europe/Copenhagen"))
    parts = [f"The current date and time is {now.strftime('%A, %-d %B %Y %H:%M')} (Copenhagen time)."]

    tracked_qls = [ql for ql in ctx.deps.quest_lines.list() if ql.status == "tracked"]
    if tracked_qls:
        parts.append("\n## Tracked Quest Lines")
        for ql in tracked_qls:
            line = f"\n### {ql.title}"
            if ql.description:
                line += f"\n{ql.description}"
            if ql.notes:
                line += f"\n*Notes: {ql.notes}*"
            parts.append(line)

    tracked_quests = [q for q in ctx.deps.quests.list() if q.status == "tracked"]
    if tracked_quests:
        parts.append("\n## Tracked Quests")
        for q in tracked_quests:
            line = f"\n### {q.title}"
            if q.description:
                line += f"\n{q.description}"
            if q.notes:
                line += f"\n*Notes: {q.notes}*"
            parts.append(line)

    return "\n".join(parts)


# --- Task tools ---

@agent.tool
async def create_task(
    ctx: RunContext[AppDeps],
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
    """Create a single action. Tasks belong to quests (quest_id), never directly to quest lines. Size uses Fibonacci scale: 1, 2, 3, 5, 8, 13, 21."""
    response_cache.invalidate()
    return compact(ctx.deps.tasks.create(
        title, description, due_date, quest_id,
        deadline_type, deadline_note, defer_until,
        energy, recurrence, review_interval, size,
    ))


@agent.tool
async def list_tasks(ctx: RunContext[AppDeps], include_old_completed: bool = False) -> list[dict]:
    """List tasks. By default excludes tasks completed before today."""
    return compact_list(ctx.deps.tasks.list(include_old_completed))


@agent.tool
async def update_task(
    ctx: RunContext[AppDeps],
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
    """Update any fields on a task. Valid statuses: todo, in_progress, done."""
    response_cache.invalidate()
    result = ctx.deps.tasks.update(
        task_id, title, status, description, due_date,
        deadline_type, deadline_note, defer_until,
        energy, recurrence, review_interval, notes, size, quest_id,
    )
    return compact(result) if result else None


# --- Quest tools ---

@agent.tool
async def create_quest(
    ctx: RunContext[AppDeps],
    title: str,
    description: str | None = None,
    status: str = "available",
    quest_line_id: str | None = None,
    size: int | None = None,
) -> Quest:
    """Create a multi-step outcome. Valid statuses: available, current, tracked, done. Size uses Fibonacci scale: 1, 2, 3, 5, 8, 13, 21."""
    response_cache.invalidate()
    return compact(ctx.deps.quests.create(title, description, status, quest_line_id, size))


@agent.tool
async def list_quests(
    ctx: RunContext[AppDeps],
    include_done: bool = False,
    quest_line_id: str | None = None,
) -> list[dict]:
    """List quests. By default excludes completed ones."""
    return compact_list(ctx.deps.quests.list(include_done, quest_line_id))


@agent.tool
async def update_quest(
    ctx: RunContext[AppDeps],
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
    """Update any fields on a quest. Valid statuses: available, current, tracked, done."""
    response_cache.invalidate()
    result = ctx.deps.quests.update(
        quest_id, title, status, description, due_date,
        deadline_type, deadline_note, defer_until,
        energy, recurrence, review_interval, notes, quest_line_id, size,
    )
    return compact(result) if result else None


# --- Quest Line tools ---

@agent.tool
async def create_quest_line(
    ctx: RunContext[AppDeps],
    title: str,
    description: str | None = None,
    status: str = "available",
) -> QuestLine:
    """Create a long-running project. Valid statuses: available, current, tracked, done."""
    response_cache.invalidate()
    return compact(ctx.deps.quest_lines.create(title, description, status))


@agent.tool
async def list_quest_lines(ctx: RunContext[AppDeps], include_done: bool = False) -> list[dict]:
    """List quest lines. By default excludes completed ones."""
    return compact_list(ctx.deps.quest_lines.list(include_done))


@agent.tool
async def update_quest_line(
    ctx: RunContext[AppDeps],
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
    """Update any fields on a quest line. Valid statuses: available, current, tracked, done. Supports review_interval (days between reviews) and defer_until."""
    response_cache.invalidate()
    result = ctx.deps.quest_lines.update(
        quest_line_id, title, status, description, due_date,
        deadline_type, deadline_note, defer_until,
        energy, recurrence, review_interval, notes,
    )
    return compact(result) if result else None


# --- Review tools ---

@agent.tool
async def mark_reviewed(ctx: RunContext[AppDeps], item_type: str, item_id: str) -> bool:
    """Mark an item as reviewed today. item_type must be 'task', 'quest', or 'quest_line'."""
    response_cache.invalidate()
    if item_type == "task":
        return ctx.deps.tasks.mark_reviewed(item_id) is not None
    elif item_type == "quest":
        return ctx.deps.quests.mark_reviewed(item_id) is not None
    elif item_type == "quest_line":
        return ctx.deps.quest_lines.mark_reviewed(item_id) is not None
    return False


@agent.tool
async def flag_for_review(ctx: RunContext[AppDeps], item_type: str, item_id: str) -> bool:
    """Flag an item to appear at the top of the review queue immediately. Clears last_reviewed and sets review_interval to 1 if unset. item_type must be 'task', 'quest', or 'quest_line'."""
    response_cache.invalidate()
    if item_type == "task":
        return ctx.deps.tasks.flag_for_review(item_id) is not None
    elif item_type == "quest":
        return ctx.deps.quests.flag_for_review(item_id) is not None
    elif item_type == "quest_line":
        return ctx.deps.quest_lines.flag_for_review(item_id) is not None
    return False


@agent.tool
async def radar(ctx: RunContext[AppDeps]) -> dict:
    """Get a structured overview of everything that needs attention: overdue deadlines, upcoming deadlines, items overdue for review, newly undeferred items, and recurring items due."""
    return get_radar()


@agent.tool
async def next_review_item(ctx: RunContext[AppDeps]) -> dict | None:
    """Get the single item most overdue for review. Returns None if nothing needs reviewing."""
    return get_next_review_item()


# --- Inbox tools ---

@agent.tool
async def create_inbox_item(ctx: RunContext[AppDeps], content: str) -> dict:
    """Capture something into the inbox without processing it yet."""
    response_cache.invalidate()
    return compact(ctx.deps.inbox.create(content))


@agent.tool
async def get_next_inbox_item(ctx: RunContext[AppDeps], max_energy: str | None = None) -> dict | None:
    """Get the next unprocessed inbox item. Optionally filter by max energy level (low, medium, high)."""
    item = ctx.deps.inbox.get_next(max_energy)
    return compact(item) if item else None


@agent.tool
async def get_next_item(ctx: RunContext[AppDeps]) -> dict | None:
    """Get the next item that needs attention: inbox items first, then the most overdue review item. Returns the item with a 'kind' field ('inbox' or 'review'), or None if nothing needs attention."""
    inbox = ctx.deps.inbox.get_next()
    if inbox:
        return {"kind": "inbox", **compact(inbox)}
    review = get_next_review_item()
    if review:
        return {"kind": "review", **review}
    return None


@agent.tool
async def list_inbox_items(ctx: RunContext[AppDeps]) -> list[dict]:
    """List all unprocessed inbox items. Use when the user wants an overview; use get_next_inbox_item to process them one at a time."""
    return [{"id": i.id, "content": i.content, "energy": i.energy, "created_at": str(i.created_at.date())} for i in ctx.deps.inbox.list_unprocessed()]


@agent.tool
async def update_inbox_item(
    ctx: RunContext[AppDeps],
    item_id: str,
    status: str | None = None,
    energy: str | None = None,
) -> dict | None:
    """Update an inbox item. Valid status values: 'processed' (handled), 'discarded' (dismissed), 'unprocessed' (default). Do NOT use 'closed', 'done', or any other value."""
    response_cache.invalidate()
    result = ctx.deps.inbox.update(item_id, status, energy)
    return compact(result) if result else None


# --- Subject tools ---

@agent.tool
async def create_subject(
    ctx: RunContext[AppDeps],
    title: str,
    contents: str,
    summary: str,
    state: str = "open",
) -> dict:
    """Create a new subject. summary is a single sentence used in the system prompt — keep it concise. contents is the full memory."""
    response_cache.invalidate()
    return compact(ctx.deps.subjects.create(title, contents, summary, state))


@agent.tool
async def update_subject(
    ctx: RunContext[AppDeps],
    subject_id: str,
    title: str | None = None,
    contents: str | None = None,
    summary: str | None = None,
    state: str | None = None,
) -> dict | None:
    """Update a subject. Always update summary when updating contents — it is what gets shown in context."""
    response_cache.invalidate()
    result = ctx.deps.subjects.update(subject_id, title, contents, summary, state)
    return compact(result) if result else None


@agent.tool
async def list_subjects(ctx: RunContext[AppDeps]) -> list[dict]:
    """List all subjects (open and closed) with id, title, state and last_discussed. Use get_subject to retrieve full contents."""
    return compact_list(ctx.deps.subjects.list())


@agent.tool
async def get_subject(ctx: RunContext[AppDeps], subject_id: str) -> dict | None:
    """Retrieve the full contents of a subject."""
    s = ctx.deps.subjects.get(subject_id)
    return compact(s) if s else None


# --- Helpers ---

def compact(item) -> dict:
    return item.model_dump(mode="json", exclude_none=True)

def compact_list(items) -> list[dict]:
    return [compact(i) for i in items]

_TOOL_LABELS = {
    "create_task": "Task created",
    "update_task": "Task updated",
    "create_quest": "Quest created",
    "update_quest": "Quest updated",
    "create_quest_line": "Quest line created",
    "update_quest_line": "Quest line updated",
    "create_subject": "Subject created",
    "update_subject": "Subject updated",
    "create_inbox_item": "Inbox item added",
    "update_inbox_item": "Inbox item updated",
    "mark_reviewed": "Marked reviewed",
    "flag_for_review": "Flagged for review",
}

_ID_ARGS = {"task_id", "quest_id", "quest_line_id", "subject_id", "item_id", "item_type"}
_SKIP_FIELDS = {"id", "created_at", "completed_at", "last_reviewed", "title", "content", "quest_line_id", "quest_id"}
_CREATE_TOOLS = {"create_task", "create_quest", "create_quest_line", "create_subject", "create_inbox_item"}

def extract_tool_events(result) -> list[str]:
    # Collect tool return values keyed by tool_call_id
    returns: dict[str, any] = {}
    for msg in result.all_messages():
        for part in getattr(msg, "parts", []):
            if hasattr(part, "tool_call_id") and hasattr(part, "content") and not hasattr(part, "args"):
                try:
                    returns[part.tool_call_id] = json.loads(part.content)
                except Exception:
                    returns[part.tool_call_id] = None

    events = []
    for msg in result.all_messages():
        for part in getattr(msg, "parts", []):
            name = getattr(part, "tool_name", None)
            if name not in _TOOL_LABELS or not hasattr(part, "args"):
                continue
            label = _TOOL_LABELS[name]
            try:
                if hasattr(part, "args_as_dict"):
                    args = part.args_as_dict()
                else:
                    raw = getattr(part, "args", {})
                    args = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
            except Exception:
                args = {}
            ret = returns.get(getattr(part, "tool_call_id", None))

            # Get item name from return value (most reliable) or args
            item_name = None
            if isinstance(ret, dict):
                item_name = ret.get("title") or ret.get("content")
            if not item_name:
                item_name = args.get("title") or args.get("content")

            if name in _CREATE_TOOLS:
                # For creates, show all meaningful fields from the return value
                if isinstance(ret, dict):
                    changes = {k: v for k, v in ret.items() if k not in _SKIP_FIELDS and v is not None}
                else:
                    changes = {k: v for k, v in args.items() if k not in _ID_ARGS and v is not None and k not in ("title", "content")}
            else:
                # For updates, show what was explicitly changed
                changes = {k: v for k, v in args.items() if k not in _ID_ARGS and v is not None and k not in ("title", "content")}

            parts_str = label
            if item_name:
                parts_str += f": {item_name}"
            if changes:
                parts_str += " (" + ", ".join(f"{k}: {v}" for k, v in changes.items()) + ")"
            events.append(parts_str)
    return events


# --- Logging ---

def log_run(label: str, result) -> None:
    usage = result.usage()
    logger.info(
        "[%s] tokens — input: %s, output: %s, total: %s",
        label,
        usage.request_tokens,
        usage.response_tokens,
        usage.total_tokens,
    )
    try:
        messages_json = ModelMessagesTypeAdapter.dump_json(result.all_messages(), indent=2)
        usage_dict = {"request_tokens": usage.request_tokens, "response_tokens": usage.response_tokens, "total_tokens": usage.total_tokens}
        with open("debug.log", "wb") as f:
            f.write(b'{"label": "' + label.encode() + b'", "usage": ')
            f.write(json.dumps(usage_dict).encode())
            f.write(b', "messages": ')
            f.write(messages_json)
            f.write(b"}")
    except Exception as e:
        logger.warning("Could not write debug.log: %s", e)


# --- API ---

class HistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[HistoryMessage] = []
    energy_level: str | None = None


class ChatResponse(BaseModel):
    response: str
    tool_events: list[str] = []


class InboxRequest(BaseModel):
    content: str


def build_history(history: list[HistoryMessage]):
    result = []
    for msg in history:
        if msg.role == "user":
            result.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
        else:
            result.append(ModelResponse(parts=[TextPart(content=msg.content)]))
    return result


@app.post("/inbox")
async def add_to_inbox(request: InboxRequest) -> dict:
    response_cache.invalidate()
    item = deps.inbox.create(request.content)
    return {"id": item.id}


class InitialRequest(BaseModel):
    mode: str
    force: bool = False
    energy_level: str | None = None


@app.post("/initial")
async def initial(request: InitialRequest) -> ChatResponse:
    if not request.force:
        cached = response_cache.get(request.mode)
        if cached:
            return ChatResponse(response=cached)
    prompt, hidden = build_initial_prompt(request.mode, request.energy_level)
    if prompt is None:
        return ChatResponse(response=_empty_message(request.mode, hidden, request.energy_level))
    modified_before = response_cache._last_modified
    result = await agent.run(prompt, deps=deps, model_settings=CACHE_SETTINGS)
    log_run(f"initial:{request.mode}", result)
    if response_cache._last_modified == modified_before:
        response_cache.set(request.mode, result.output)
    return ChatResponse(response=result.output, tool_events=extract_tool_events(result))


@app.post("/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    history = build_history(request.history)
    message = request.message
    if request.energy_level:
        message = f"[My current energy level: {request.energy_level}]\n{message}"
    result = await agent.run(message, deps=deps, message_history=history, model_settings=CACHE_SETTINGS)
    log_run("chat", result)
    return ChatResponse(response=result.output, tool_events=extract_tool_events(result))
