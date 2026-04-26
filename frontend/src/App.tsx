import { useState, useRef, useEffect } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Mode = "inbox" | "processing" | "quests" | "dashboard";
type Energy = "low" | "medium" | "high";

interface TaskData {
  id: string;
  title: string;
  threat_level: "high" | "medium" | "low";
  energy: string | null;
  due_days: number | null;
  deadline_type: string | null;
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
  // inbox
  content?: string;
  energy?: string;
  // review
  type?: "task" | "quest" | "quest_line";
  title?: string;
  description?: string;
  notes?: string;
  status?: string;
  days_overdue?: number;
  last_reviewed?: string;
  tasks?: ReviewSubItem[];
  quests?: ReviewSubItem[];
}

interface ReviewState {
  item: ReviewItem | null;
  inbox_count: number;
  review_count: number;
}

interface Message {
  role: "user" | "assistant" | "tool";
  content: string;
  quest_data?: QuestOverviewData;
}

const MODES: { id: Mode; label: string }[] = [
  { id: "inbox", label: "Inbox Drop" },
  { id: "processing", label: "Processing" },
  { id: "quests", label: "Quests" },
  { id: "dashboard", label: "Dashboard" },
];

const ENERGY_LEVELS: Energy[] = ["low", "medium", "high"];

const AUTO_PROMPTS: Partial<Record<Mode, string>> = {
  processing: "Let's process my inbox and work through anything that needs review.",
  quests: "What should I work on next?",
};

const THREAT_STYLE: Record<string, React.CSSProperties> = {
  high:   { background: "#fee2e2", color: "#991b1b", border: "1px solid #fca5a5" },
  low:    { background: "#dcfce7", color: "#166534", border: "1px solid #86efac" },
};

function ThreatChip({ level }: { level: string }) {
  const style = THREAT_STYLE[level];
  if (!style) return null;
  return (
    <span style={{ fontSize: "0.7rem", padding: "0.1rem 0.4rem", borderRadius: 4, marginLeft: "0.3rem", ...style }}>
      {level}
    </span>
  );
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

function DueChip({ days }: { days: number; type: string | null }) {
  const label = days < 0 ? `${Math.abs(days)}d overdue` : days === 0 ? "today" : `${days}d`;
  const style: React.CSSProperties = days <= 0
    ? { background: "#fee2e2", color: "#991b1b", border: "1px solid #fca5a5" }
    : days <= 3
    ? { background: "#fef3c7", color: "#92400e", border: "1px solid #fcd34d" }
    : { background: "#f3f4f6", color: "#6b7280", border: "1px solid #d1d5db" };
  return (
    <span style={{ fontSize: "0.7rem", padding: "0.1rem 0.4rem", borderRadius: 4, marginLeft: "0.3rem", ...style }}>
      {label}
    </span>
  );
}

function TaskRow({ t }: { t: TaskData }) {
  return (
    <div style={{ display: "flex", alignItems: "center", padding: "0.25rem 0", flexWrap: "wrap" }}>
      <span style={{ fontSize: "0.9rem" }}>{t.title}</span>
      <ThreatChip level={t.threat_level} />
      {t.energy && <Battery level={t.energy} />}
      {t.due_days != null && <DueChip days={t.due_days} type={t.deadline_type} />}
    </div>
  );
}

function QuestBlock({ q }: { q: QuestData }) {
  return (
    <div style={{ marginBottom: "0.75rem" }}>
      <div style={{ fontWeight: 600, fontSize: "0.85rem", color: "#374151", marginBottom: "0.25rem" }}>{q.title}</div>
      {q.tasks.length === 0
        ? <div style={{ color: "#9ca3af", fontSize: "0.8rem", paddingLeft: "0.75rem" }}>no tasks</div>
        : q.tasks.map(t => <div key={t.id} style={{ paddingLeft: "0.75rem" }}><TaskRow t={t} /></div>)
      }
    </div>
  );
}

function QuestOverview({ data }: { data: QuestOverviewData }) {
  const empty = data.quest_lines.length === 0 && data.standalone_quests.length === 0 && data.questless_tasks.length === 0;

  return (
    <div style={{ fontSize: "0.9rem" }}>
      {empty && <div style={{ color: "#6b7280" }}>No tracked quests right now. Reply to explore others.</div>}

      {data.quest_lines.map(ql => (
        <div key={ql.id} style={{ marginBottom: "1.25rem" }}>
          <div style={{ fontWeight: 700, fontSize: "0.95rem", marginBottom: "0.5rem", borderBottom: "1px solid #e5e7eb", paddingBottom: "0.2rem" }}>{ql.title}</div>
          {ql.quests.length === 0
            ? <div style={{ color: "#9ca3af", fontSize: "0.8rem" }}>no active quests</div>
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
          <div style={{ fontWeight: 700, fontSize: "0.95rem", marginBottom: "0.5rem", borderBottom: "1px solid #e5e7eb", paddingBottom: "0.2rem" }}>Unassigned tasks</div>
          {data.questless_tasks.map(t => <TaskRow key={t.id} t={t} />)}
        </div>
      )}

      {(data.hidden > 0 || data.deferred > 0) && (
        <div style={{ color: "#9ca3af", fontSize: "0.75rem", marginTop: "0.5rem" }}>
          {[data.hidden > 0 && `${data.hidden} hidden by energy filter`, data.deferred > 0 && `${data.deferred} deferred`].filter(Boolean).join(", ")}
        </div>
      )}

      <div style={{ color: "#9ca3af", fontSize: "0.8rem", marginTop: "0.75rem" }}>Reply to get suggestions, or ask anything.</div>
    </div>
  );
}

const TYPE_LABEL: Record<string, string> = {
  task: "Task",
  quest: "Quest",
  quest_line: "Quest Line",
  inbox: "Inbox",
};

function Processing({ energy: _energy }: { energy: Energy | null }) {
  const [state, setState] = useState<ReviewState | null>(null);
  const [acting, setActing] = useState(false);
  const [aiMessages, setAiMessages] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [aiInput, setAiInput] = useState("");
  const [aiLoading, setAiLoading] = useState(false);

  async function load() {
    const data = await fetch("/review/next").then(r => r.json());
    setState(data);
    setAiMessages([]);
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
    setAiMessages([]);
    setActing(false);
  }

  async function askAI() {
    const text = aiInput.trim();
    if (!text || aiLoading || !state?.item) return;
    setAiInput("");
    setAiLoading(true);

    const item = state.item;
    const context = item.kind === "inbox"
      ? `[Processing inbox item: "${item.content}"]\n`
      : `[Processing ${TYPE_LABEL[item.type ?? ""] ?? item.type}: "${item.title}" — ${item.days_overdue}d overdue. Status: ${item.status}. Description: ${item.description ?? "none"}. Notes: ${item.notes ?? "none"}.]\n`;

    setAiMessages(prev => [...prev, { role: "user", content: text }]);

    const { response } = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: context + text, history: [], mode: "processing" }),
    }).then(r => r.json());

    setAiMessages(prev => [...prev, { role: "assistant", content: response }]);
    setAiLoading(false);
    // refresh item in case AI updated any fields
    const fresh = await fetch("/review/next").then(r => r.json());
    setState(s => s ? { ...fresh } : s);
  }

  if (!state) return <div style={{ color: "#999" }}>Loading...</div>;

  const { item, inbox_count, review_count } = state;

  return (
    <div>
      {/* Info box */}
      <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem", padding: "0.6rem 0.9rem", background: "#f8fafc", border: "1px solid #e5e7eb", borderRadius: 8, fontSize: "0.85rem", color: "#6b7280" }}>
        <span><strong style={{ color: inbox_count > 0 ? "#374151" : undefined }}>{inbox_count}</strong> inbox</span>
        <span><strong style={{ color: review_count > 0 ? "#374151" : undefined }}>{review_count}</strong> review</span>
        <button onClick={load} style={{ marginLeft: "auto", fontSize: "0.8rem", padding: "0.1rem 0.5rem", cursor: "pointer" }}>↺ Refresh</button>
      </div>

      {/* Item card */}
      {!item ? (
        <div style={{ color: "#6b7280", fontSize: "0.9rem", padding: "1.5rem 0" }}>All caught up — nothing needs attention.</div>
      ) : (
        <div style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: "1rem", marginBottom: "1rem" }}>
          {/* Header row */}
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.75rem" }}>
            <span style={{ fontSize: "0.7rem", fontWeight: 700, padding: "0.15rem 0.5rem", borderRadius: 4, background: "#e0f2fe", color: "#0369a1", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              {item.kind === "inbox" ? "Inbox" : TYPE_LABEL[item.type ?? ""] ?? item.type}
            </span>
            {item.kind === "review" && item.days_overdue !== undefined && (
              <span style={{ fontSize: "0.75rem", color: item.days_overdue > 14 ? "#991b1b" : "#92400e" }}>
                {item.days_overdue}d overdue
              </span>
            )}
          </div>

          {/* Title / content */}
          <div style={{ fontWeight: 700, fontSize: "1rem", marginBottom: "0.5rem" }}>
            {item.kind === "inbox" ? item.content : item.title}
          </div>

          {/* Detail fields */}
          {item.description && (
            <div style={{ fontSize: "0.875rem", color: "#374151", marginBottom: "0.4rem" }}>{item.description}</div>
          )}
          {item.notes && (
            <div style={{ fontSize: "0.85rem", color: "#6b7280", fontStyle: "italic", marginBottom: "0.4rem" }}>Notes: {item.notes}</div>
          )}
          {item.last_reviewed && (
            <div style={{ fontSize: "0.75rem", color: "#9ca3af", marginBottom: "0.5rem" }}>Last reviewed: {item.last_reviewed}</div>
          )}

          {/* Subtasks */}
          {item.tasks && item.tasks.length > 0 && (
            <div style={{ marginBottom: "0.5rem" }}>
              <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "#6b7280", marginBottom: "0.25rem" }}>TASKS</div>
              {item.tasks.map(t => (
                <div key={t.id} style={{ fontSize: "0.85rem", color: "#374151", paddingLeft: "0.5rem", marginBottom: "0.15rem" }}>
                  • {t.title} <span style={{ color: "#9ca3af" }}>({t.status})</span>
                </div>
              ))}
            </div>
          )}

          {/* Sub-quests */}
          {item.quests && item.quests.length > 0 && (
            <div style={{ marginBottom: "0.5rem" }}>
              <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "#6b7280", marginBottom: "0.25rem" }}>QUESTS</div>
              {item.quests.map(q => (
                <div key={q.id} style={{ fontSize: "0.85rem", color: "#374151", paddingLeft: "0.5rem", marginBottom: "0.15rem" }}>
                  • {q.title} <span style={{ color: "#9ca3af" }}>({q.status})</span>
                </div>
              ))}
            </div>
          )}

          {/* Action buttons */}
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
            {item.kind === "inbox" ? (
              <>
                <button onClick={() => advance("processed")} disabled={acting} style={{ padding: "0.3rem 0.75rem", background: "#0070f3", color: "white", border: "none", borderRadius: 5, cursor: "pointer", fontSize: "0.85rem" }}>Processed</button>
                <button onClick={() => advance("discard")} disabled={acting} style={{ padding: "0.3rem 0.75rem", background: "#f3f4f6", color: "#374151", border: "1px solid #d1d5db", borderRadius: 5, cursor: "pointer", fontSize: "0.85rem" }}>Discard</button>
              </>
            ) : (
              <>
                <button onClick={() => advance("mark")} disabled={acting} style={{ padding: "0.3rem 0.75rem", background: "#0070f3", color: "white", border: "none", borderRadius: 5, cursor: "pointer", fontSize: "0.85rem" }}>Mark reviewed</button>
                <button onClick={() => advance("defer")} disabled={acting} style={{ padding: "0.3rem 0.75rem", background: "#f3f4f6", color: "#374151", border: "1px solid #d1d5db", borderRadius: 5, cursor: "pointer", fontSize: "0.85rem" }}>Defer 7d</button>
                {item.type === "task" && (
                  <button onClick={() => advance("done")} disabled={acting} style={{ padding: "0.3rem 0.75rem", background: "#10b981", color: "white", border: "none", borderRadius: 5, cursor: "pointer", fontSize: "0.85rem" }}>Mark done</button>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* AI chat */}
      {item && (
        <div style={{ marginTop: "0.5rem" }}>
          {aiMessages.length > 0 && (
            <div style={{ marginBottom: "0.75rem" }}>
              {aiMessages.map((m, i) => (
                <div key={i} style={{ marginBottom: "0.5rem", textAlign: m.role === "user" ? "right" : "left" }}>
                  <span style={{ display: "inline-block", padding: "0.4rem 0.7rem", borderRadius: 8, background: m.role === "user" ? "#0070f3" : "#f0f0f0", color: m.role === "user" ? "white" : "black", maxWidth: "85%", fontSize: "0.9rem", textAlign: "left" }}>
                    {m.role === "user" ? m.content : <Markdown remarkPlugins={[remarkGfm]}>{m.content}</Markdown>}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <input
              style={{ flex: 1, padding: "0.5rem", fontSize: "0.9rem" }}
              value={aiInput}
              onChange={e => setAiInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.ctrlKey) askAI(); }}
              placeholder="Ask AI about this item…"
              disabled={aiLoading}
            />
            <button onClick={askAI} disabled={aiLoading} style={{ padding: "0.5rem 0.75rem", fontSize: "0.9rem" }}>
              {aiLoading ? "…" : "Ask"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

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
        style={{ width: "100%", height: 140, fontSize: "1rem", padding: "0.5rem", boxSizing: "border-box" }}
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && e.ctrlKey && drop()}
        placeholder="What's on your mind? No AI, just capture."
        autoFocus
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "0.5rem" }}>
        <span style={{ color: "#999", fontSize: "0.8rem" }}>Ctrl+Enter to drop</span>
        <button onClick={drop} disabled={status === "saving"}>
          {status === "saved" ? "Dropped ✓" : status === "saving" ? "..." : "Drop"}
        </button>
      </div>
    </div>
  );
}

function Dashboard() {
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

  if (loading) return <div style={{ color: "#999" }}>Loading...</div>;

  if (groups.length === 0) {
    return (
      <div style={{ color: "#6b7280", fontSize: "0.9rem" }}>
        <p>No suggested tasks yet.</p>
        <p>Go to Processing or Quests and ask the agent to tag tasks for the dashboard — for example: "Tag some tasks for the dashboard based on what makes sense to do today."</p>
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "0.75rem" }}>
        <button onClick={load} style={{ fontSize: "0.8rem", padding: "0.2rem 0.6rem" }}>Refresh</button>
      </div>
      <div style={{ display: "grid", gap: "1rem" }}>
        {groups.map(g => (
          <div key={g.tag} style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: "1rem" }}>
            <div style={{ fontWeight: 700, fontSize: "0.95rem", marginBottom: "0.75rem", color: "#374151" }}>
              {g.tag}
            </div>
            {g.tasks.map((t, i) => (
              <div
                key={t.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "0.4rem 0",
                  borderTop: i > 0 ? "1px solid #f3f4f6" : undefined,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", flex: 1, minWidth: 0, flexWrap: "wrap" }}>
                  <span style={{ fontSize: "0.9rem" }}>{t.title}</span>
                  <ThreatChip level={t.threat_level} />
                  {t.energy && <Battery level={t.energy} />}
                  {t.due_days != null && <DueChip days={t.due_days} type={t.deadline_type} />}
                </div>
                <button
                  onClick={() => complete(t.id)}
                  style={{
                    marginLeft: "0.75rem",
                    padding: "0.2rem 0.6rem",
                    fontSize: "0.8rem",
                    background: "#10b981",
                    color: "white",
                    border: "none",
                    borderRadius: 4,
                    cursor: "pointer",
                    flexShrink: 0,
                  }}
                >
                  Done
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

interface ChatProps {
  mode?: Mode;
  energy: Energy | null;
  autoPrompt?: string;
}

function Chat({ mode, energy, autoPrompt }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const energyRef = useRef(energy);

  useEffect(() => { energyRef.current = energy; }, [energy]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);
  useEffect(() => { if (mode && autoPrompt) fireInitial(false); }, []);

  async function fireInitial(force: boolean) {
    setLoading(true);
    setMessages([]);
    try {
      const { response, tool_events, quest_data } = await fetch("/initial", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, force, energy_level: energyRef.current }),
      }).then((r) => r.json());
      setMessages([
        ...(tool_events ?? []).map((e: string) => ({ role: "tool" as const, content: e })),
        { role: "assistant", content: response, quest_data: quest_data ?? undefined },
      ]);
    } catch (e) {
      setMessages([
        { role: "assistant", content: "Something went wrong. Try again with ↺." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function sendMessage(text: string, history: Message[]) {
    setLoading(true);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    const cleanHistory = history.filter((m) => m.role !== "tool" && !m.quest_data);
    const { response, tool_events } = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: cleanHistory, energy_level: energyRef.current, mode }),
    }).then((r) => r.json());
    setMessages((prev) => [
      ...prev,
      ...(tool_events ?? []).map((e: string) => ({ role: "tool" as const, content: e })),
      { role: "assistant", content: response },
    ]);
    setLoading(false);
  }

  async function send(fresh = false) {
    const text = input.trim();
    if (!text || loading) return;
    const history = fresh ? [] : messages;
    setInput("");
    if (fresh) setMessages([]);
    await sendMessage(text, history);
  }

  function restart() {
    if (loading) return;
    setInput("");
    if (mode && autoPrompt) fireInitial(true);
    else { setMessages([]); }
  }

  return (
    <div>
      <div style={{ minHeight: 400, marginBottom: "1rem" }}>
        {messages.map((msg, i) => (
          msg.role === "tool" ? (
            <div key={i} style={{ marginBottom: "0.4rem", textAlign: "left" }}>
              <span style={{
                display: "inline-block",
                padding: "0.2rem 0.6rem",
                borderRadius: 4,
                background: "#eef4ff",
                color: "#4a6fa5",
                fontSize: "0.78rem",
                fontFamily: "monospace",
                borderLeft: "3px solid #99bbee",
              }}>
                {msg.content}
              </span>
            </div>
          ) : (
            <div key={i} style={{ marginBottom: "0.75rem", textAlign: msg.role === "user" ? "right" : "left" }}>
              {msg.quest_data ? (
                <QuestOverview data={msg.quest_data} />
              ) : (
                <span style={{
                  display: "inline-block",
                  padding: "0.5rem 0.75rem",
                  borderRadius: 8,
                  background: msg.role === "user" ? "#0070f3" : "#f0f0f0",
                  color: msg.role === "user" ? "white" : "black",
                  maxWidth: "85%",
                  textAlign: "left",
                }}>
                  {msg.role === "user" ? msg.content : <Markdown remarkPlugins={[remarkGfm]}>{msg.content}</Markdown>}
                </span>
              )}
            </div>
          )
        ))}
        {loading && <div style={{ color: "#999", marginBottom: "0.75rem" }}>...</div>}
        <div ref={bottomRef} />
      </div>

      <div style={{ display: "flex", gap: "0.5rem" }}>
        <input
          style={{ flex: 1, padding: "0.5rem", fontSize: "1rem" }}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.ctrlKey && e.shiftKey) send(true);
            else if (e.key === "Enter" && !e.ctrlKey) send();
          }}
          placeholder="Reply… (Ctrl+Shift+Enter to send as new conversation)"
          disabled={loading}
          autoFocus
        />
        <button onClick={() => send()} disabled={loading}>
          {loading ? "..." : "Send"}
        </button>
        <button onClick={restart} disabled={loading} title="Clear and restart">
          ↺
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const [mode, setMode] = useState<Mode>("processing");
  const [energy, setEnergy] = useState<Energy | null>(null);

  function toggleEnergy(e: Energy) {
    setEnergy((prev) => (prev === e ? null : e));
  }

  return (
    <div style={{ maxWidth: 700, margin: "0 auto", padding: "1rem", fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <h1 style={{ margin: 0, fontSize: "1.4rem" }}>Muninn</h1>
        <div style={{ display: "flex", gap: "0.25rem", alignItems: "center" }}>
          <span style={{ fontSize: "0.8rem", color: "#666", marginRight: "0.25rem" }}>Energy:</span>
          {ENERGY_LEVELS.map((e) => (
            <button
              key={e}
              onClick={() => toggleEnergy(e)}
              style={{
                padding: "0.2rem 0.5rem",
                fontSize: "0.8rem",
                background: energy === e ? "#0070f3" : "#eee",
                color: energy === e ? "white" : "#333",
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

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}>
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            style={{
              flex: 1,
              padding: "0.5rem",
              background: mode === m.id ? "#0070f3" : "#eee",
              color: mode === m.id ? "white" : "#333",
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
        <Dashboard />
      </div>
      <div style={{ display: mode === "quests" ? "block" : "none" }}>
        <Chat mode="quests" energy={energy} autoPrompt={AUTO_PROMPTS["quests"]} />
      </div>
    </div>
  );
}
