import { useState } from "react";
import PaperCard from "./PaperCard";

export default function LibraryView({ papers, loading, selectedId, onOpen, onDelete }) {
  const [filter, setFilter] = useState("");
  const f = filter.trim().toLowerCase();
  const shown = f
    ? papers.filter((p) => `${p.title} ${p.authors.join(" ")}`.toLowerCase().includes(f))
    : papers;

  if (loading) return <p className="text-sm text-slate-500">Loading library…</p>;
  if (!papers.length)
    return (
      <p className="rounded-md border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
        Your library is empty. Save papers from Search or upload a PDF.
      </p>
    );

  return (
    <div className="space-y-3">
      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder={`Filter ${papers.length} saved papers…`}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
      />
      {shown.map((p) => (
        <PaperCard key={p.id} paper={p} selected={p.id === selectedId} onOpen={() => onOpen(p.id)}>
          <button
            onClick={() => onOpen(p.id)}
            className="rounded-md bg-indigo-600 px-3 py-1 text-sm text-white hover:bg-indigo-700"
          >
            Summarize & ask
          </button>
          <button
            onClick={() => {
              if (confirm(`Remove "${p.title}" from your library?`)) onDelete(p.id);
            }}
            className="rounded-md border border-slate-300 px-3 py-1 text-sm text-slate-600 hover:bg-slate-50"
          >
            Remove
          </button>
        </PaperCard>
      ))}
    </div>
  );
}
