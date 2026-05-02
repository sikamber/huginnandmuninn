import { useState, useRef, useEffect } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Mode = "inbox" | "processing" | "quests" | "dashboard";
type Energy = "low" | "medium" | "high";

interface TaskData {
  id: string;
  title: string;
  threat_level: "high" | "medium" | "low";
  energy?: string;
  due_days?: number;
  deadline_type?: string;
}

interface QuestData {
  id: string;
  title: string;
  status: string;
  tasks: TaskData[];
}

interface QuestLineData {
  id: string;
  title: string;
  quests: QuestData[];
}

interface QuestOverviewData {
  quest_lines: QuestLineData[];
  standalone_quests: QuestData[];
  questless_tasks: TaskData[];
  hidden: number;
  deferred: number;
}

interface DashboardGroup {
  tag: string;
  tasks: TaskData[];
}

interface ReviewSubItem {
  id: string;
  title: string;
  status: string;
  description?: string;
}

interface ReviewItem {
  kind: "inbox" | "review";
  id: string;
  content?: string;
  energy?: string;
  threat_level?: string;
  type?: "task" | "quest" | "quest_line";
  title?: string;
  description?: string;
  notes?: string;
  user_review_notes?: string;
  status?: string;
  days_overdue?: number;
  next_user_review?: string;
  tasks?: ReviewSubItem[];
  quests?: ReviewSubItem[];
}

interface ReviewState {
  item: ReviewItem | null;
  inbox_count: number;
  review_count: number;
}

interface AiMessage {
  role: "user" | "assistant" | "tool";
  content: string;
  historyContent?: string;
}

const MODES: { id: Mode; label: string }[] = [
  { id: "inbox", label: "Inbox Drop" },
  { id: "processing", label: "Processing" },
  { id: "quests", label: "Quests" },
  { id: "dashboard", label: "Dashboard" },
];

const ENERGY_LEVELS: Energy[] = ["low", "medium", "high"];

// ---- Chip helpers ----------------------------------------------------------

function ThreatChip({ level }: { level: string }) {
  if (level === "high") return (
    <span style={{ fontSize: "0.7rem", padding: "0.1rem 0.4rem", borderRadius: 4, marginLeft: "0.3rem", background: "var(--c-chip-danger-bg)", color: "var(--c-chip-danger-text)", border: "1px solid var(--c-chip-danger-border)" }}>
      {level}
    </span>
  );
  if (level === "low") return (
    <span style={{ fontSize: "0.7rem", padding: "0.1rem 0.4rem", borderRadius: 4, marginLeft: "0.3rem", background: "var(--c-chip-success-bg)", color: "var(--c-chip-success-text)", border: "1px solid var(--c-chip-success-border)" }}>
      {level}
    </span>
  );
  return null;
}

const BATTERY_COLOR: Record<string, string> = {
  low:    "#3b82f6",
  medium: "#f59e0b",
  high:   "#ef4444",
};
const BATTERY_FILL: Record<string, number> = { low: 1, medium: 2, high: 3 };

function Battery({ level }: { level: string }) {
  const color = BATTERY_COLOR[level] ?? "#9ca3af";
  const filled = BATTERY_FILL[level] ?? 0;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", marginLeft: "0.35rem", verticalAlign: "middle" }}>
      <span style={{ display: "inline-flex", alignItems: "center", border: `1.5px solid ${color}`, borderRadius: 3, padding: "2px 3px", gap: 2 }}>
        {[1, 2, 3].map(i => (
          <span key={i} style={{ width: 4, height: 9, borderRadius: 1, background: i <= filled ? color : "transparent", border: `1px solid ${color}` }} />
        ))}
      </span>
      <span style={{ width: 2, height: 5, background: color, borderRadius: "0 1px 1px 0" }} />
    </span>
  );
}

function DueChip({ days }: { days: number }) {
  const label = days < 0 ? `${Math.abs(days)}d overdue` : days === 0 ? "today" : `${days}d`;
  const [bg, text, border] = days <= 0
    ? ["var(--c-chip-danger-bg)", "var(--c-chip-danger-text)", "var(--c-chip-danger-border)"]
    : days <= 3
    ? ["var(--c-chip-warn-bg)", "var(--c-chip-warn-text)", "var(--c-chip-warn-border)"]
    : ["var(--c-chip-neutral-bg)", "var(--c-chip-neutral-text)", "var(--c-chip-neutral-border)"];
  return (
    <span style={{ fontSize: "0.7rem", padding: "0.1rem 0.4rem", borderRadius: 4, marginLeft: "0.3rem", background: bg, color: text, border: `1px solid ${border}` }}>
      {label}
    </span>
  );
}

function TaskRow({ t }: { t: TaskData }) {
  return (
    <div style={{ display: "flex", alignItems: "center", padding: "0.25rem 0", flexWrap: "wrap" }}>
      <span style={{ fontSize: "0.9rem", color: "var(--c-text-primary)" }}>{t.title}</span>
      <ThreatChip level={t.threat_level} />
      {t.energy && <Battery level={t.energy} />}
      {t.due_days != null && <DueChip days={t.due_days} />}
    </div>
  );
}

function QuestBlock({ q }: { q: QuestData }) {
  return (
    <div style={{ marginBottom: "0.75rem" }}>
      <div style={{ fontWeight: 600, fontSize: "0.85rem", color: "var(--c-text-secondary)", marginBottom: "0.25rem" }}>{q.title}</div>
      {q.tasks.length === 0
        ? <div style={{ color: "var(--c-text-dim)", fontSize: "0.8rem", paddingLeft: "0.75rem" }}>no tasks</div>
        : q.tasks.map(t => <div key={t.id} style={{ paddingLeft: "0.75rem" }}><TaskRow t={t} /></div>)
      }
    </div>
  );
}

function QuestOverview({ data }: { data: QuestOverviewData }) {
  const empty = data.quest_lines.length === 0 && data.standalone_quests.length === 0 && data.questless_tasks.length === 0;

  return (
    <div style={{ fontSize: "0.9rem" }}>
      {empty && <div style={{ color: "var(--c-text-muted)" }}>No tracked quests right now.</div>}

      {data.quest_lines.map(ql => (
        <div key={ql.id} style={{ marginBottom: "1.25rem" }}>
          <div style={{ fontWeight: 700, fontSize: "0.95rem", marginBottom: "0.5rem", borderBottom: "1px solid var(--c-border)", paddingBottom: "0.2rem", color: "var(--c-text-primary)" }}>{ql.title}</div>
          {ql.quests.length === 0
            ? <div style={{ color: "var(--c-text-dim)", fontSize: "0.8rem" }}>no active quests</div>
            : ql.quests.map(q => <QuestBlock key={q.id} q={q} />)
          }
        </div>
      ))}

      {data.standalone_quests.map(q => (
        <div key={q.id} style={{ marginBottom: "1.25rem" }}>
          <QuestBlock q={q} />
        </div>
      ))}

      {data.questless_tasks.length > 0 && (
        <div style={{ marginBottom: "1.25rem" }}>
          <div style={{ fontWeight: 700, fontSize: "0.95rem", marginBottom: "0.5rem", borderBottom: "1px solid var(--c-border)", paddingBottom: "0.2rem", color: "var(--c-text-primary)" }}>Unassigned tasks</div>
          {data.questless_tasks.map(t => <TaskRow key={t.id} t={t} />)}
        </div>
      )}

      {(data.hidden > 0 || data.deferred > 0) && (
        <div style={{ color: "var(--c-text-dim)", fontSize: "0.75rem", marginTop: "0.5rem" }}>
          {[data.hidden > 0 && `${data.hidden} hidden by energy filter`, data.deferred > 0 && `${data.deferred} deferred`].filter(Boolean).join(", ")}
        </div>
      )}
    </div>
  );
}

// ---- Shared AI chat --------------------------------------------------------

interface AiChatProps {
  mode: string;
  energy: Energy | null;
  getContext?: () => string;
  onRefresh?: () => void;
}

function AiChat({ mode, energy, getContext, onRefresh }: AiChatProps) {
  const [messages, setMessages] = useState<AiMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  async function send(fresh: boolean) {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");

    const isFirstInThread = fresh || messages.length === 0;
    const contextPrefix = isFirstInThread && getContext ? getContext() : "";
    const apiMessage = contextPrefix + text;

    const history = fresh
      ? []
      : messages.reduce<{ role: string; content: string }[]>((acc, m, i, arr) => {
          if (m.role === "tool") return acc;
          if (m.role === "assistant") {
            // Merge any preceding tool events into the assistant message for context
            const toolsBefore: string[] = [];
            for (let j = i - 1; j >= 0 && arr[j].role === "tool"; j--) {
              toolsBefore.unshift(arr[j].content);
            }
            const content = toolsBefore.length > 0
              ? `[Tool calls: ${toolsBefore.join("; ")}]\n\n${m.content}`
              : m.content;
            return [...acc, { role: m.role, content }];
          }
          return [...acc, { role: m.role, content: m.content }];
        }, []);

    if (fresh) setMessages([]);

    setMessages(prev => [...prev, { role: "user", content: text }]);
    setLoading(true);

    try {
      const { response, tool_events } = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: apiMessage, history, energy_level: energy, mode }),
      }).then(r => r.json());

      setMessages(prev => [
        ...prev,
        ...(tool_events ?? []).map((e: string) => ({ role: "tool" as const, content: e })),
        { role: "assistant", content: response },
      ]);
      if (tool_events?.length > 0) onRefresh?.();
    } finally {
      setLoading(false);
    }
  }

  const hasMessages = messages.length > 0;

  return (
    <div style={{ marginTop: "1.25rem", borderTop: "1px solid var(--c-border)", paddingTop: "1rem" }}>
      {hasMessages && (
        <div style={{ marginBottom: "0.75rem" }}>
          {messages.map((m, i) =>
            m.role === "tool" ? (
              <div key={i} style={{ marginBottom: "0.3rem" }}>
                <span style={{ display: "inline-block", padding: "0.2rem 0.6rem", borderRadius: 4, background: "var(--c-tool-bg)", color: "var(--c-tool-color)", fontSize: "0.78rem", fontFamily: "monospace", borderLeft: "3px solid var(--c-tool-border)" }}>
                  {m.content}
                </span>
              </div>
            ) : (
              <div key={i} style={{ marginBottom: "0.6rem", textAlign: m.role === "user" ? "right" : "left" }}>
                <span style={{ display: "inline-block", padding: "0.4rem 0.7rem", borderRadius: 8, background: m.role === "user" ? "#0070f3" : "var(--c-bubble-ai)", color: m.role === "user" ? "white" : "var(--c-bubble-ai-text)", maxWidth: "85%", textAlign: "left", fontSize: "0.9rem" }}>
                  {m.role === "user"
                    ? m.content
                    : <Markdown remarkPlugins={[remarkGfm]}>{m.content}</Markdown>}
                </span>
              </div>
            )
          )}
          {loading && <div style={{ color: "var(--c-text-dim)", fontSize: "0.9rem" }}>…</div>}
        </div>
      )}
      {!hasMessages && loading && <div style={{ color: "var(--c-text-dim)", fontSize: "0.9rem", marginBottom: "0.5rem" }}>…</div>}
      <div style={{ display: "flex", gap: "0.5rem" }}>
        <input
          style={{ flex: 1, padding: "0.45rem 0.6rem", fontSize: "0.9rem", border: "1px solid var(--c-input-border)", borderRadius: 5, background: "var(--c-input-bg)", color: "var(--c-text-primary)" }}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); send(true); }
            else if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(false); }
          }}
          placeholder={hasMessages ? "Reply… (Ctrl+Enter for new thread)" : "Ask AI about this view…"}
          disabled={loading}
        />
        {hasMessages && (
          <button onClick={() => setMessages([])} disabled={loading} style={{ padding: "0.45rem 0.6rem", fontSize: "0.85rem", borderRadius: 5, cursor: "pointer", background: "var(--c-bg-muted)", color: "var(--c-text-secondary)", border: "1px solid var(--c-border)" }}>
            New
          </button>
        )}
        <button onClick={() => send(false)} disabled={loading} style={{ padding: "0.45rem 0.75rem", fontSize: "0.85rem", borderRadius: 5, cursor: "pointer" }}>
          {loading ? "…" : "Ask"}
        </button>
      </div>
      <div ref={bottomRef} />
    </div>
  );
}

// ---- Processing ------------------------------------------------------------

const TYPE_LABEL: Record<string, string> = {
  task: "Task",
  quest: "Quest",
  quest_line: "Quest Line",
  inbox: "Inbox",
};

function Processing({ energy }: { energy: Energy | null }) {
  const [state, setState] = useState<ReviewState | null>(null);
  const [acting, setActing] = useState(false);

  async function load() {
    const data = await fetch("/review/next").then(r => r.json());
    setState(data);
  }

  useEffect(() => { load(); }, []);

  async function advance(action: string) {
    if (!state?.item || acting) return;
    setActing(true);
    const { kind, id, type } = state.item;
    const data = await fetch("/review/advance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, item_id: id, item_type: type ?? null, action }),
    }).then(r => r.json());
    setState(data);
    setActing(false);
  }

  if (!state) return <div style={{ color: "var(--c-text-dim)" }}>Loading…</div>;

  const { item, inbox_count, review_count } = state;

  function getContext() {
    if (!item) return "";
    if (item.kind === "inbox") {
      return `[Processing inbox item: "${item.content}"]\n`;
    }
    return `[Processing ${TYPE_LABEL[item.type ?? ""] ?? item.type}: "${item.title}" — ${item.days_overdue}d overdue. Status: ${item.status}. Description: ${item.description ?? "none"}. Notes: ${item.notes ?? "none"}. Review note: ${item.user_review_notes ?? "none"}.]\n`;
  }

  return (
    <div>
      {/* counters */}
      <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem", padding: "0.6rem 0.9rem", background: "var(--c-bg-subtle)", border: "1px solid var(--c-border)", borderRadius: 8, fontSize: "0.85rem", color: "var(--c-text-muted)" }}>
        <span><strong style={{ color: inbox_count > 0 ? "var(--c-text-primary)" : undefined }}>{inbox_count}</strong> inbox</span>
        <span><strong style={{ color: review_count > 0 ? "var(--c-text-primary)" : undefined }}>{review_count}</strong> review</span>
        <button onClick={load} style={{ marginLeft: "auto", fontSize: "0.8rem", padding: "0.1rem 0.5rem", cursor: "pointer" }}>↺ Refresh</button>
      </div>

      {/* item card */}
      {!item ? (
        <div style={{ color: "var(--c-text-muted)", fontSize: "0.9rem", padding: "1.5rem 0" }}>All caught up — nothing needs attention.</div>
      ) : (
        <div style={{ border: "1px solid var(--c-border)", borderRadius: 8, padding: "1rem", marginBottom: "0.25rem", background: "var(--c-bg-card)" }}>
          {/* header */}
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.75rem", flexWrap: "wrap" }}>
            <span style={{ fontSize: "0.7rem", fontWeight: 700, padding: "0.15rem 0.5rem", borderRadius: 4, background: "var(--c-badge-bg)", color: "var(--c-badge-color)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              {item.kind === "inbox" ? "Inbox" : TYPE_LABEL[item.type ?? ""] ?? item.type}
            </span>
            {item.threat_level && <ThreatChip level={item.threat_level} />}
            {item.kind === "review" && item.days_overdue !== undefined && (
              <span style={{ fontSize: "0.75rem", color: item.days_overdue > 14 ? "var(--c-chip-danger-text)" : "var(--c-chip-warn-text)" }}>
                {item.days_overdue}d overdue
              </span>
            )}
          </div>

          {/* title / content */}
          {item.kind === "inbox" ? (
            <div style={{ fontSize: "0.9rem", color: "var(--c-text-primary)", marginBottom: "0.5rem" }}>
              <Markdown remarkPlugins={[remarkGfm]}>{item.content ?? ""}</Markdown>
            </div>
          ) : (
            <div style={{ fontWeight: 700, fontSize: "1rem", marginBottom: "0.5rem", color: "var(--c-text-primary)" }}>
              {item.title}
            </div>
          )}

          {item.description && (
            <div style={{ fontSize: "0.875rem", color: "var(--c-text-secondary)", marginBottom: "0.4rem" }}>{item.description}</div>
          )}
          {item.notes && (
            <div style={{ fontSize: "0.85rem", color: "var(--c-text-muted)", fontStyle: "italic", marginBottom: "0.4rem" }}>Notes: {item.notes}</div>
          )}
          {item.user_review_notes && (
            <div style={{ fontSize: "0.85rem", color: "var(--c-review-note-color)", background: "var(--c-review-note-bg)", padding: "0.3rem 0.5rem", borderRadius: 4, marginBottom: "0.4rem" }}>
              Review note: {item.user_review_notes}
            </div>
          )}
          {item.next_user_review && (
            <div style={{ fontSize: "0.75rem", color: "var(--c-text-dim)", marginBottom: "0.5rem" }}>Scheduled: {item.next_user_review}</div>
          )}

          {item.tasks && item.tasks.length > 0 && (
            <div style={{ marginBottom: "0.5rem" }}>
              <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--c-text-muted)", marginBottom: "0.25rem" }}>TASKS</div>
              {item.tasks.map(t => (
                <div key={t.id} style={{ fontSize: "0.85rem", color: "var(--c-text-secondary)", paddingLeft: "0.5rem", marginBottom: "0.15rem" }}>
                  • {t.title} <span style={{ color: "var(--c-text-dim)" }}>({t.status})</span>
                </div>
              ))}
            </div>
          )}

          {item.quests && item.quests.length > 0 && (
            <div style={{ marginBottom: "0.5rem" }}>
              <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--c-text-muted)", marginBottom: "0.25rem" }}>QUESTS</div>
              {item.quests.map(q => (
                <div key={q.id} style={{ fontSize: "0.85rem", color: "var(--c-text-secondary)", paddingLeft: "0.5rem", marginBottom: "0.15rem" }}>
                  • {q.title} <span style={{ color: "var(--c-text-dim)" }}>({q.status})</span>
                </div>
              ))}
            </div>
          )}

          {/* actions */}
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
            {item.kind === "inbox" ? (
              <>
                <button onClick={() => advance("processed")} disabled={acting} style={{ padding: "0.3rem 0.75rem", background: "#0070f3", color: "white", border: "none", borderRadius: 5, cursor: "pointer", fontSize: "0.85rem" }}>Mark processed</button>
                <button onClick={() => advance("discard")} disabled={acting} style={{ padding: "0.3rem 0.75rem", background: "var(--c-bg-muted)", color: "var(--c-text-secondary)", border: "1px solid var(--c-border)", borderRadius: 5, cursor: "pointer", fontSize: "0.85rem" }}>Discard</button>
                {item.threat_level !== "low" && (
                  <button onClick={() => advance("defer_threat")} disabled={acting} style={{ padding: "0.3rem 0.75rem", background: "var(--c-bg-muted)", color: "var(--c-text-secondary)", border: "1px solid var(--c-border)", borderRadius: 5, cursor: "pointer", fontSize: "0.85rem" }}>Defer to low</button>
                )}
              </>
            ) : (
              <>
                <button onClick={() => advance("mark")} disabled={acting} style={{ padding: "0.3rem 0.75rem", background: "#0070f3", color: "white", border: "none", borderRadius: 5, cursor: "pointer", fontSize: "0.85rem" }}>Mark reviewed</button>
                <button onClick={() => advance("defer")} disabled={acting} style={{ padding: "0.3rem 0.75rem", background: "var(--c-bg-muted)", color: "var(--c-text-secondary)", border: "1px solid var(--c-border)", borderRadius: 5, cursor: "pointer", fontSize: "0.85rem" }}>Defer 7d</button>
                {item.type === "task" && (
                  <button onClick={() => advance("done")} disabled={acting} style={{ padding: "0.3rem 0.75rem", background: "#10b981", color: "white", border: "none", borderRadius: 5, cursor: "pointer", fontSize: "0.85rem" }}>Mark done</button>
                )}
              </>
            )}
          </div>
        </div>
      )}

      <AiChat key={item?.id ?? "empty"} mode="processing" energy={energy} getContext={getContext} onRefresh={load} />
    </div>
  );
}

// ---- Inbox Drop ------------------------------------------------------------

function InboxDrop() {
  const [content, setContent] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");

  async function drop() {
    if (!content.trim() || status === "saving") return;
    setStatus("saving");
    await fetch("/inbox", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    setContent("");
    setStatus("saved");
    setTimeout(() => setStatus("idle"), 2000);
  }

  return (
    <div>
      <textarea
        style={{ width: "100%", height: 140, fontSize: "1rem", padding: "0.5rem", boxSizing: "border-box", background: "var(--c-input-bg)", color: "var(--c-text-primary)", border: "1px solid var(--c-input-border)", borderRadius: 4 }}
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && e.ctrlKey && drop()}
        placeholder="What's on your mind? No AI, just capture."
        autoFocus
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "0.5rem" }}>
        <span style={{ color: "var(--c-text-dim)", fontSize: "0.8rem" }}>Ctrl+Enter to drop</span>
        <button onClick={drop} disabled={status === "saving"}>
          {status === "saved" ? "Dropped" : status === "saving" ? "..." : "Drop"}
        </button>
      </div>
    </div>
  );
}

// ---- Dashboard -------------------------------------------------------------

function Dashboard({ energy }: { energy: Energy | null }) {
  const [groups, setGroups] = useState<DashboardGroup[]>([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const data = await fetch("/dashboard").then(r => r.json());
      setGroups(data.groups ?? []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function complete(taskId: string) {
    await fetch(`/tasks/${taskId}/complete`, { method: "POST" });
    setGroups(prev =>
      prev
        .map(g => ({ ...g, tasks: g.tasks.filter(t => t.id !== taskId) }))
        .filter(g => g.tasks.length > 0)
    );
  }

  function getContext() {
    if (groups.length === 0) return "";
    const lines = ["[Current dashboard:"];
    for (const g of groups) {
      lines.push(`Group "${g.tag}":`);
      for (const t of g.tasks) lines.push(`  - ${t.title}`);
    }
    lines.push("]");
    return lines.join("\n") + "\n";
  }

  return (
    <div>
      {loading && groups.length === 0 ? (
        <div style={{ color: "var(--c-text-dim)" }}>Loading…</div>
      ) : (
        <>
          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "0.75rem" }}>
            <button onClick={load} style={{ fontSize: "0.8rem", padding: "0.2rem 0.6rem" }}>
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
          {groups.length === 0 ? (
            <div style={{ color: "var(--c-text-muted)", fontSize: "0.9rem" }}>
              <p>No suggested tasks yet.</p>
              <p style={{ marginTop: "0.5rem" }}>Ask the AI below to tag tasks for the dashboard — for example: "Tag some tasks for the dashboard based on what makes sense to do today."</p>
            </div>
          ) : (
            <div style={{ display: "grid", gap: "1rem" }}>
              {groups.map(g => (
                <div key={g.tag} style={{ border: "1px solid var(--c-border)", borderRadius: 8, padding: "1rem", background: "var(--c-bg-card)" }}>
                  <div style={{ fontWeight: 700, fontSize: "0.95rem", marginBottom: "0.75rem", color: "var(--c-text-primary)" }}>
                    {g.tag}
                  </div>
                  {g.tasks.map((t, i) => (
                    <div
                      key={t.id}
                      style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0.4rem 0", borderTop: i > 0 ? "1px solid var(--c-border-light)" : undefined }}
                    >
                      <div style={{ display: "flex", alignItems: "center", flex: 1, minWidth: 0, flexWrap: "wrap" }}>
                        <span style={{ fontSize: "0.9rem", color: "var(--c-text-primary)" }}>{t.title}</span>
                        <ThreatChip level={t.threat_level} />
                        {t.energy && <Battery level={t.energy} />}
                        {t.due_days != null && <DueChip days={t.due_days} />}
                      </div>
                      <button
                        onClick={() => complete(t.id)}
                        style={{ marginLeft: "0.75rem", padding: "0.2rem 0.6rem", fontSize: "0.8rem", background: "#10b981", color: "white", border: "none", borderRadius: 4, cursor: "pointer", flexShrink: 0 }}
                      >
                        Done
                      </button>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      <AiChat mode="dashboard" energy={energy} getContext={getContext} onRefresh={load} />
    </div>
  );
}

// ---- Quests ----------------------------------------------------------------

function Quests({ energy }: { energy: Energy | null }) {
  const [questData, setQuestData] = useState<QuestOverviewData | null>(null);

  async function load() {
    const params = energy ? `?energy=${energy}` : "";
    const data = await fetch(`/quests${params}`).then(r => r.json());
    setQuestData(data);
  }

  useEffect(() => { load(); }, [energy]);

  function getContext() {
    if (!questData) return "";
    const lines = ["[Current quest overview:"];
    for (const ql of questData.quest_lines) {
      lines.push(`Quest Line: ${ql.title}`);
      for (const q of ql.quests) {
        lines.push(`  Quest: ${q.title} (${q.status})`);
        for (const t of q.tasks) lines.push(`    Task: ${t.title}${t.threat_level === "high" ? " [HIGH]" : ""}`);
      }
    }
    for (const q of questData.standalone_quests) {
      lines.push(`Quest: ${q.title} (${q.status})`);
      for (const t of q.tasks) lines.push(`  Task: ${t.title}`);
    }
    if (questData.questless_tasks.length > 0) {
      lines.push("Unassigned tasks:");
      for (const t of questData.questless_tasks) lines.push(`  - ${t.title}`);
    }
    lines.push("]");
    return lines.join("\n") + "\n";
  }

  if (!questData) return <div style={{ color: "var(--c-text-dim)" }}>Loading…</div>;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "0.75rem" }}>
        <button onClick={load} style={{ fontSize: "0.8rem", padding: "0.2rem 0.6rem" }}>Refresh</button>
      </div>
      <QuestOverview data={questData} />
      <AiChat mode="quests" energy={energy} getContext={getContext} onRefresh={load} />
    </div>
  );
}

// ---- App shell -------------------------------------------------------------

export default function App() {
  const [mode, setMode] = useState<Mode>("dashboard");
  const [energy, setEnergy] = useState<Energy | null>(null);

  function toggleEnergy(e: Energy) {
    setEnergy((prev) => (prev === e ? null : e));
  }

  return (
    <div style={{ maxWidth: 700, margin: "0 auto", padding: "1rem", fontFamily: "sans-serif" }}>
      {/* header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <h1 style={{ margin: 0, fontSize: "1.4rem", color: "var(--c-text-primary)" }}>Muninn</h1>
        <div style={{ display: "flex", gap: "0.25rem", alignItems: "center" }}>
          <span style={{ fontSize: "0.8rem", color: "var(--c-text-muted)", marginRight: "0.25rem" }}>Energy:</span>
          {ENERGY_LEVELS.map((e) => (
            <button
              key={e}
              onClick={() => toggleEnergy(e)}
              style={{
                padding: "0.2rem 0.5rem",
                fontSize: "0.8rem",
                background: energy === e ? "#0070f3" : "var(--c-btn-inactive-bg)",
                color: energy === e ? "white" : "var(--c-btn-inactive-text)",
                border: "none",
                borderRadius: 4,
                cursor: "pointer",
              }}
            >
              {e}
            </button>
          ))}
        </div>
      </div>

      {/* mode tabs */}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}>
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            style={{
              flex: 1,
              padding: "0.5rem",
              background: mode === m.id ? "#0070f3" : "var(--c-btn-inactive-bg)",
              color: mode === m.id ? "white" : "var(--c-btn-inactive-text)",
              border: "none",
              borderRadius: 6,
              cursor: "pointer",
              fontWeight: mode === m.id ? "bold" : "normal",
              fontSize: "0.9rem",
            }}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div style={{ display: mode === "inbox" ? "block" : "none" }}>
        <InboxDrop />
      </div>
      <div style={{ display: mode === "processing" ? "block" : "none" }}>
        <Processing energy={energy} />
      </div>
      <div style={{ display: mode === "dashboard" ? "block" : "none" }}>
        <Dashboard energy={energy} />
      </div>
      <div style={{ display: mode === "quests" ? "block" : "none" }}>
        <Quests energy={energy} />
      </div>
    </div>
  );
}
