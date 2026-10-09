import { useRef, useState } from "react";
import { api } from "../api";
import PaperCard from "./PaperCard";

export default function UploadView({ onOpen, onLibraryChanged }) {
  const inputRef = useRef(null);
  const [state, setState] = useState({ status: "idle" });
  const [dragging, setDragging] = useState(false);

  async function upload(file) {
    if (!file) return;
    if (file.type && file.type !== "application/pdf") {
      setState({ status: "error", error: "Please choose a PDF file." });
      return;
    }
    setState({ status: "loading", name: file.name });
    try {
      const { paper, created } = await api.uploadPdf(file);
      setState({ status: "done", paper, created });
      onLibraryChanged();
    } catch (err) {
      setState({ status: "error", error: err.message });
    }
  }

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          upload(e.dataTransfer.files[0]);
        }}
        className={`rounded-lg border-2 border-dashed p-10 text-center ${
          dragging ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-white"
        }`}
      >
        <p className="text-sm text-slate-600">Drag a research paper PDF here, or</p>
        <button
          onClick={() => inputRef.current?.click()}
          disabled={state.status === "loading"}
          className="mt-3 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
        >
          Choose PDF
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={(e) => {
            upload(e.target.files[0]);
            e.target.value = "";
          }}
        />
        <p className="mt-3 text-xs text-slate-400">
          Title, authors, year and abstract are extracted automatically (max 25 MB).
        </p>
      </div>

      {state.status === "loading" && (
        <p className="text-sm text-slate-500">Uploading and extracting metadata from {state.name}…</p>
      )}
      {state.status === "error" && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{state.error}</p>}
      {state.status === "done" && (
        <div className="space-y-2">
          {state.created ? (
            <p className="text-sm font-medium text-emerald-700">Added to your library:</p>
          ) : (
            <p className="text-sm font-medium text-slate-700">This PDF is already in your library:</p>
          )}
          <PaperCard paper={state.paper} onOpen={() => onOpen(state.paper.id)}>
            <button
              onClick={() => onOpen(state.paper.id)}
              className="rounded-md bg-indigo-600 px-3 py-1 text-sm text-white hover:bg-indigo-700"
            >
              Summarize & ask
            </button>
          </PaperCard>
        </div>
      )}
    </div>
  );
}
