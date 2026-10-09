import { useState } from "react";
import { api } from "../api";
import PaperCard from "./PaperCard";

const FALLBACK_TEXT = {
  s2_rate_limited: "Semantic Scholar is rate limiting requests",
  s2_timeout: "Semantic Scholar timed out",
  s2_network_error: "Semantic Scholar could not be reached",
  s2_auth_error: "Semantic Scholar rejected the API key (check SEMANTIC_SCHOLAR_API_KEY)",
};

export default function SearchView({ onOpen, onLibraryChanged }) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState({ status: "idle" });
  const [saving, setSaving] = useState({});

  async function runSearch(e) {
    e.preventDefault();
    if (!query.trim()) return;
    setState({ status: "loading" });
    try {
      const data = await api.search(query.trim());
      setState({ status: "done", ...data });
    } catch (err) {
      setState({ status: "error", error: err.message });
    }
  }

  async function save(result, index) {
    setSaving((s) => ({ ...s, [index]: true }));
    try {
      const { saved_id: _ignored, ...meta } = result;
      const paper = await api.savePaper(meta);
      setState((s) => ({
        ...s,
        results: s.results.map((r, i) => (i === index ? { ...r, saved_id: paper.id } : r)),
      }));
      onLibraryChanged();
    } catch (err) {
      alert(`Could not save: ${err.message}`);
    } finally {
      setSaving((s) => ({ ...s, [index]: false }));
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={runSearch} className="flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search papers by keyword or topic, e.g. low-rank adaptation"
          className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
        />
        <button
          disabled={state.status === "loading"}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
        >
          {state.status === "loading" ? "Searching…" : "Search"}
        </button>
      </form>

      {state.status === "error" && (
        <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{state.error}</p>
      )}

      {state.status === "done" && (
        <>
          <p className="text-xs text-slate-500">
            {state.results.length} results from{" "}
            <span className="font-medium">{state.source === "arxiv" ? "arXiv" : "Semantic Scholar"}</span>
            {state.fallback_reason && (
              <span className="ml-1 rounded bg-amber-50 px-1.5 py-0.5 text-amber-800">
                fallback: {FALLBACK_TEXT[state.fallback_reason] || state.fallback_reason}
              </span>
            )}
          </p>
          {state.results.length === 0 && <p className="text-sm text-slate-500">No papers matched this query.</p>}
          <div className="space-y-3">
            {state.results.map((r, i) => (
              <PaperCard key={r.external_id || i} paper={r}>
                {r.saved_id ? (
                  <button
                    onClick={() => onOpen(r.saved_id)}
                    className="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-1 text-sm text-emerald-800 hover:bg-emerald-100"
                  >
                    ✓ Saved · Open
                  </button>
                ) : (
                  <button
                    onClick={() => save(r, i)}
                    disabled={saving[i]}
                    className="rounded-md bg-slate-900 px-3 py-1 text-sm text-white hover:bg-slate-700 disabled:opacity-60"
                  >
                    {saving[i] ? "Saving…" : "Save to library"}
                  </button>
                )}
              </PaperCard>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
