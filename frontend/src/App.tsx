import { useState, useRef, useEffect } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Mode = "inbox" | "radar" | "review" | "quests";
type Energy = "low" | "medium" | "high";

interface Message {
  role: "user" | "assistant" | "tool";
  content: string;
}

const MODES: { id: Mode; label: string }[] = [
  { id: "inbox", label: "Inbox Drop" },
  { id: "radar", label: "Radar Check" },
  { id: "review", label: "Review" },
  { id: "quests", label: "Quests" },
];

const ENERGY_LEVELS: Energy[] = ["low", "medium", "high"];

const AUTO_PROMPTS: Partial<Record<Mode, string>> = {
  radar: "Give me a radar check — what needs my attention right now?",
  review: "Let's process my inbox and work through anything that needs review.",
  quests: "What should I work on next?",
};

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
    setMessages([{ role: "user", content: autoPrompt! }]);
    try {
      const { response, tool_events } = await fetch("/initial", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, force, energy_level: energyRef.current }),
      }).then((r) => r.json());
      setMessages([
        { role: "user", content: autoPrompt! },
        ...(tool_events ?? []).map((e: string) => ({ role: "tool" as const, content: e })),
        { role: "assistant", content: response },
      ]);
    } catch (e) {
      setMessages([
        { role: "user", content: autoPrompt! },
        { role: "assistant", content: "Something went wrong. Try again with ↺." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function sendMessage(text: string, history: Message[]) {
    setLoading(true);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    const cleanHistory = history.filter((m) => m.role !== "tool");
    const { response, tool_events } = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: cleanHistory, energy_level: energyRef.current }),
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
  const [mode, setMode] = useState<Mode>("radar");
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
      {(["radar", "review", "quests"] as Mode[]).map((m) => (
        <div key={m} style={{ display: mode === m ? "block" : "none" }}>
          <Chat mode={m} energy={energy} autoPrompt={AUTO_PROMPTS[m]} />
        </div>
      ))}
    </div>
  );
}
