from contextlib import asynccontextmanager
from datetime import date, datetime
import json
import logging
import os
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("huginn")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
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
from inbox import InboxStore
from quests import Quest, QuestLine, QuestLineStore, QuestStore
from review import build_review_summary, get_next_review_item
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


ENERGY_ORDER = {"low": 0, "medium": 1, "high": 2}

def _within_energy(item_energy: str | None, max_energy: str | None) -> bool:
    if max_energy is None or item_energy is None:
        return True
    return ENERGY_ORDER.get(item_energy, 0) <= ENERGY_ORDER.get(max_energy, 2)


def build_quest_data(quest_line_store, quest_store, task_store, energy_level: str | None = None) -> dict:
    today = date.today()
    all_qls = quest_line_store.list()
    all_quests = quest_store.list()
    all_tasks = task_store.list()

    tracked_qls = [ql for ql in all_qls if ql.status == "tracked" and _within_energy(ql.energy, energy_level)]
    tracked_quests = [q for q in all_quests if q.status == "tracked" and _within_energy(q.energy, energy_level)]
    tracked_ql_ids = {ql.id for ql in tracked_qls}

    hidden = sum(1 for i in all_qls + all_quests if not _within_energy(i.energy, energy_level))
    deferred = sum(1 for i in all_qls + all_quests if i.defer_until and i.defer_until > today)

    tasks_by_quest: dict[str, list] = {}
    questless_tasks = []
    for t in all_tasks:
        if t.status != "done" and _within_energy(t.energy, energy_level) and not (t.defer_until and t.defer_until > today):
            if t.quest_id:
                tasks_by_quest.setdefault(t.quest_id, []).append(t)
            else:
                questless_tasks.append(t)

    def _task_dict(t) -> dict:
        return {
            "id": t.id,
            "title": t.title,
            "threat_level": t.threat_level,
            "energy": t.energy,
            "due_days": (t.due_date - today).days if t.due_date else None,
            "deadline_type": t.deadline_type,
        }

    def _quest_dict(q) -> dict:
        return {
            "id": q.id,
            "title": q.title,
            "status": q.status,
            "tasks": [_task_dict(t) for t in tasks_by_quest.get(q.id, [])],
        }

    quest_lines_data = []
    for ql in tracked_qls:
        ql_quests = [q for q in all_quests if q.quest_line_id == ql.id and q.status != "done" and _within_energy(q.energy, energy_level)]
        quest_lines_data.append({
            "id": ql.id,
            "title": ql.title,
            "quests": [_quest_dict(q) for q in ql_quests],
        })

    standalone = [_quest_dict(q) for q in tracked_quests if q.quest_line_id not in tracked_ql_ids]

    return {
        "quest_lines": quest_lines_data,
        "standalone_quests": standalone,
        "questless_tasks": [_task_dict(t) for t in questless_tasks],
        "hidden": hidden,
        "deferred": deferred,
    }


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
- `threat_level` (tasks only): high / medium (default) / low — urgency/importance of the task; high-threat tasks should be surfaced prominently on the quests page
- `recurrence`: days between expected recurrences (track via last_reviewed)
- `review_interval`: days between reviews — quest lines support this just like tasks and quests; call mark_reviewed after genuinely reviewing an item
- `notes`: your working memory on an item — observations, hunches, context across conversations
- `context_tags` (tasks only): list of context strings that surface the task on the dashboard (e.g. ["Needs to happen today", "Self-care options", "Deep focus"]). Set when tagging tasks for the dashboard; clear (empty list) when no longer relevant.
- `evaluated` (tasks only): set true when you have reviewed and confirmed a task's completion — distinct from the user simply marking it done via the dashboard button.

## Dashboard
When the user asks you to suggest tasks for the dashboard, set `context_tags` on relevant tasks. Tags are flexible strings describing the context in which the task fits best. Keep tag names consistent across tasks so they group into the same card. Clear tags (pass an empty list) from tasks that are no longer relevant suggestions.

## Behaviour
- Summarise meaningfully — don't just read lists back.
- Do not use emojis or emoticons in any response.
- After the user responds to a review item — whether they update it, comment on it, or just move on — you MUST call `mark_reviewed` before calling `get_next_item`. No exceptions. Do not call `get_next_item` without first calling `mark_reviewed` for the current review item.
- When reviewing items, present one at a time. Do not list everything due for review — use `next_review_item` and present only that item, then wait for the user to respond before moving on.
- When presenting a review item, surface the context already included in the response: description, notes, status, days overdue, and any tasks or quests embedded in the result. Do not call additional tools to look up subtasks — they are already there. Present as a brief narrative summary, then invite the user to reflect or respond. Do not show a numbered list of options or actions. Never mention details that are not present in the data returned by the tool.
- For initial overviews, give a high-level summary. When task data is already provided in the prompt, use it directly — do not call list_tasks again. Only call list_tasks when the user explicitly asks for tasks not already in context.
- When creating a quest or quest line, the `status` field is required — always choose a tier (tracked/current/available) based on what the user said and confirm your choice before creating. Never assume available without saying so.
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
    threat_level: str = "medium",
) -> Task:
    """Create a single action. Tasks belong to quests (quest_id), never directly to quest lines. Size uses Fibonacci scale: 1, 2, 3, 5, 8, 13, 21. threat_level: high / medium (default) / low."""
    response_cache.invalidate()
    return compact(ctx.deps.tasks.create(
        title, description, due_date, quest_id,
        deadline_type, deadline_note, defer_until,
        energy, recurrence, review_interval, size, threat_level,
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
    threat_level: str | None = None,
    context_tags: list[str] | None = None,
    evaluated: bool | None = None,
) -> Task | None:
    """Update any fields on a task. Valid statuses: todo, in_progress, done. threat_level: high / medium / low. context_tags: list of context strings for the dashboard (pass [] to clear). evaluated: set true when you have reviewed the completion."""
    response_cache.invalidate()
    result = ctx.deps.tasks.update(
        task_id, title, status, description, due_date,
        deadline_type, deadline_note, defer_until,
        energy, recurrence, review_interval, notes, size, quest_id, threat_level,
        context_tags, evaluated,
    )
    return compact(result) if result else None


# --- Quest tools ---

@agent.tool
async def create_quest(
    ctx: RunContext[AppDeps],
    title: str,
    status: str,
    description: str | None = None,
    quest_line_id: str | None = None,
    size: int | None = None,
) -> Quest:
    """Create a multi-step outcome. status is required — choose: available, current, tracked, or done. Size uses Fibonacci scale: 1, 2, 3, 5, 8, 13, 21."""
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
    status: str,
    description: str | None = None,
) -> QuestLine:
    """Create a long-running project. status is required — choose: available, current, tracked, or done."""
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

            item_name = None
            if isinstance(ret, dict):
                item_name = ret.get("title") or ret.get("content")
            if not item_name:
                item_name = args.get("title") or args.get("content")

            if name in _CREATE_TOOLS:
                if isinstance(ret, dict):
                    changes = {k: v for k, v in ret.items() if k not in _SKIP_FIELDS and v is not None}
                else:
                    changes = {k: v for k, v in args.items() if k not in _ID_ARGS and v is not None and k not in ("title", "content")}
            else:
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
    mode: str | None = None


class ChatResponse(BaseModel):
    response: str
    tool_events: list[str] = []
    quest_data: dict | None = None


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
    if request.mode == "processing":
        summary = build_review_summary(deps.inbox, deps.subjects, request.energy_level)
        return ChatResponse(response=summary)

    if request.mode == "quests":
        data = build_quest_data(deps.quest_lines, deps.quests, deps.tasks, request.energy_level)
        return ChatResponse(response="", quest_data=data)


@app.post("/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    history = build_history(request.history)
    message = request.message
    if request.energy_level:
        message = f"[My current energy level: {request.energy_level}]\n{message}"
    model_override = "anthropic:claude-haiku-4-5-20251001" if request.mode == "processing" else None
    result = await agent.run(
        message, deps=deps, message_history=history,
        model_settings=CACHE_SETTINGS, model=model_override,
    )
    log_run("chat", result)
    return ChatResponse(response=result.output, tool_events=extract_tool_events(result))


@app.get("/dashboard")
async def dashboard() -> dict:
    today = date.today()
    all_tasks = deps.tasks.list()
    active = [
        t for t in all_tasks
        if t.status not in ("done",)
        and t.context_tags
        and not (t.defer_until and t.defer_until > today)
    ]

    groups: dict[str, list] = {}
    for task in active:
        td = {
            "id": task.id,
            "title": task.title,
            "threat_level": task.threat_level,
            "energy": task.energy,
            "due_days": (task.due_date - today).days if task.due_date else None,
            "deadline_type": task.deadline_type,
        }
        for tag in task.context_tags:
            groups.setdefault(tag, []).append(td)

    return {"groups": [{"tag": tag, "tasks": tasks} for tag, tasks in groups.items()]}


@app.post("/tasks/{task_id}/complete")
async def complete_task(task_id: str) -> dict:
    result = deps.tasks.update(task_id, status="done")
    response_cache.invalidate()
    return {"ok": True} if result else {"ok": False}


# Serve frontend static files — must be mounted last, after all API routes.
if os.path.isdir("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
