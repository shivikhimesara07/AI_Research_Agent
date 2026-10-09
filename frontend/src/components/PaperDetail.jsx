import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { api } from "../api";
import { formatAuthors } from "./PaperCard";

const SUGGESTIONS = [
  "What problem does this paper address?",
  "What is the main idea of the proposed approach?",
  "What datasets are used?",
  "What are the major limitations?",
  "How does this method compare with the baselines?",
];

function BasisNote({ basis }) {
  if (basis !== "abstract") return null;
  return (
    <p className="mb-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-800">
      The full text could not be retrieved, so this is based on the abstract only. Upload the PDF for a full-text
      answer.
    </p>
  );
}

export default function PaperDetail({ paperId, onClose }) {
  const [paper, setPaper] = useState(null);
  const [error, setError] = useState(null);
  const [summary, setSummary] = useState({ status: "idle" });
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState(null);
  const [lastBasis, setLastBasis] = useState(null);
  const chatEnd = useRef(null);

  useEffect(() => {
    let cancelled = false;
    setPaper(null);
    setError(null);
    setAskError(null);
    setLastBasis(null);
    Promise.all([api.getPaper(paperId), api.messages(paperId)])
      .then(([p, msgs]) => {
        if (cancelled) return;
        setPaper(p);
        setMessages(msgs);
        setSummary(p.summary ? { status: "done", text: p.summary, basis: p.summary_basis } : { status: "idle" });
      })
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [paperId]);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, asking]);

  async function summarize(refresh = false) {
    setSummary({ status: "loading" });
    try {
      const r = await api.summarize(paperId, refresh);
      setSummary({ status: "done", text: r.summary, basis: r.summary_basis });
    } catch (err) {
      setSummary({ status: "error", error: err.message });
    }
  }

  async function ask(q) {
    const text = (q ?? question).trim();
    if (!text || asking) return;
    setQuestion("");
    setAskError(null);
    setAsking(true);
    setMessages((m) => [...m, { id: `pending-${Date.now()}`, role: "user", content: text }]);
    try {
      const r = await api.ask(paperId, text);
      setLastBasis(r.content_basis);
      setMessages(await api.messages(paperId));
    } catch (err) {
      setAskError(err.message);
      setMessages((m) => m.filter((x) => !String(x.id).startsWith("pending-")));
      setQuestion(text);
    } finally {
      setAsking(false);
    }
  }

  if (error) return <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>;
  if (!paper) return <p className="text-sm text-slate-500">Loading paper…</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold leading-snug text-slate-900">{paper.title}</h2>
          <p className="mt-1 text-sm text-slate-600">
            {formatAuthors(paper.authors, 8)}
            {paper.year ? ` · ${paper.year}` : ""}
          </p>
        </div>
        <button onClick={onClose} className="text-xl leading-none text-slate-400 hover:text-slate-700" aria-label="Close">
          ×
        </button>
      </div>

      {/* ---------- Summary ---------- */}
      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="font-semibold text-slate-900">Summary</h3>
          {summary.status === "done" ? (
            <button onClick={() => summarize(true)} className="text-xs text-indigo-600 hover:underline">
              Regenerate
            </button>
          ) : null}
        </div>
        {summary.status === "idle" && (
          <button
            onClick={() => summarize(false)}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            Generate summary
          </button>
        )}
        {summary.status === "loading" && (
          <p className="animate-pulse text-sm text-slate-500">
            Reading the paper and writing a summary… (the first run may download the PDF)
          </p>
        )}
        {summary.status === "error" && (
          <div className="text-sm text-red-700">
            {summary.error}{" "}
            <button onClick={() => summarize(false)} className="text-indigo-600 hover:underline">
              Retry
            </button>
          </div>
        )}
        {summary.status === "done" && (
          <>
            <BasisNote basis={summary.basis} />
            <div className="prose-summary text-sm leading-relaxed text-slate-800">
              <Markdown>{summary.text}</Markdown>
            </div>
          </>
        )}
      </section>

      {/* ---------- Q&A ---------- */}
      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-2 font-semibold text-slate-900">Ask about this paper</h3>
        <BasisNote basis={lastBasis} />
        <div className="max-h-[28rem] space-y-3 overflow-y-auto">
          {messages.map((m) => (
            <div key={m.id} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div
                className={`max-w-[90%] rounded-lg px-3 py-2 text-sm ${
                  m.role === "user" ? "bg-indigo-600 text-white" : "prose-summary bg-slate-100 text-slate-800"
                }`}
              >
                {m.role === "user" ? m.content : <Markdown>{m.content}</Markdown>}
              </div>
            </div>
          ))}
          {asking && <p className="animate-pulse text-sm text-slate-500">Thinking…</p>}
          <div ref={chatEnd} />
        </div>

        {messages.length === 0 && !asking && (
          <div className="mt-2 flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => ask(s)}
                className="rounded-full border border-slate-300 px-3 py-1 text-xs text-slate-700 hover:border-indigo-400 hover:bg-indigo-50"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {askError && <p className="mt-2 text-sm text-red-700">{askError}</p>}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask();
          }}
          className="mt-3 flex gap-2"
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question about this paper…"
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
          />
          <button
            disabled={asking || !question.trim()}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            Ask
          </button>
        </form>
      </section>
    </div>
  );
}
