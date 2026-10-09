import { useState } from "react";

const SOURCE_LABEL = { semantic_scholar: "Semantic Scholar", arxiv: "arXiv", upload: "Uploaded PDF" };

export function formatAuthors(authors = [], max = 6) {
  if (!authors.length) return "Unknown authors";
  if (authors.length <= max) return authors.join(", ");
  return `${authors.slice(0, max).join(", ")}, et al.`;
}

export default function PaperCard({ paper, selected = false, onOpen, children }) {
  const [expanded, setExpanded] = useState(false);
  const abstract = paper.abstract || "";
  const long = abstract.length > 360;

  return (
    <article
      className={`rounded-lg border bg-white p-4 shadow-sm transition ${
        selected ? "border-indigo-500 ring-2 ring-indigo-200" : "border-slate-200"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-semibold leading-snug text-slate-900">
          {onOpen ? (
            <button onClick={onOpen} className="text-left hover:text-indigo-700 hover:underline">
              {paper.title}
            </button>
          ) : (
            paper.title
          )}
        </h3>
        <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
          {SOURCE_LABEL[paper.source] || paper.source}
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-600">
        {formatAuthors(paper.authors)}
        {paper.year ? <span className="text-slate-400"> · {paper.year}</span> : null}
      </p>

      {abstract ? (
        <p className="mt-2 text-sm leading-relaxed text-slate-700">
          {long && !expanded ? `${abstract.slice(0, 360)}…` : abstract}
          {long && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="ml-1 text-xs font-medium text-indigo-600 hover:underline"
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          )}
        </p>
      ) : (
        <p className="mt-2 text-sm italic text-slate-400">No abstract available.</p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {paper.url && (
          <a href={paper.url} target="_blank" rel="noreferrer" className="text-sm text-indigo-600 hover:underline">
            Paper page ↗
          </a>
        )}
        {paper.pdf_url && (
          <a href={paper.pdf_url} target="_blank" rel="noreferrer" className="text-sm text-indigo-600 hover:underline">
            PDF ↗
          </a>
        )}
        <div className="ml-auto flex gap-2">{children}</div>
      </div>
    </article>
  );
}
