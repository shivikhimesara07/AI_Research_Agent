import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import LibraryView from "./components/LibraryView";
import PaperDetail from "./components/PaperDetail";
import SearchView from "./components/SearchView";
import UploadView from "./components/UploadView";

const TABS = [
  { id: "search", label: "Search" },
  { id: "library", label: "Library" },
  { id: "upload", label: "Upload PDF" },
];

export default function App() {
  const [tab, setTab] = useState("search");
  const [papers, setPapers] = useState([]);
  const [loadingLibrary, setLoadingLibrary] = useState(true);
  const [selectedId, setSelectedId] = useState(null);

  const refreshLibrary = useCallback(async () => {
    try {
      setPapers(await api.listPapers());
    } catch (err) {
      console.error("Could not load library", err);
    } finally {
      setLoadingLibrary(false);
    }
  }, []);

  useEffect(() => {
    refreshLibrary();
  }, [refreshLibrary]);

  async function deletePaper(id) {
    try {
      await api.deletePaper(id);
      if (selectedId === id) setSelectedId(null);
      refreshLibrary();
    } catch (err) {
      alert(`Could not remove: ${err.message}`);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-3">
          <h1 className="text-lg font-bold">
            <span className="text-indigo-600">◆</span> AI Research Assistant
          </h1>
          <nav className="flex gap-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium ${
                  tab === t.id ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {t.label}
                {t.id === "library" && papers.length > 0 && (
                  <span className="ml-1.5 rounded-full bg-slate-200 px-1.5 text-xs text-slate-700">{papers.length}</span>
                )}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main
        className={`mx-auto grid max-w-7xl gap-6 px-4 py-6 ${selectedId ? "lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" : ""}`}
      >
        <div className="min-w-0">
          {/* Keep views mounted so search results survive tab switches. */}
          <div hidden={tab !== "search"}>
            <SearchView onOpen={setSelectedId} onLibraryChanged={refreshLibrary} />
          </div>
          <div hidden={tab !== "library"}>
            <LibraryView
              papers={papers}
              loading={loadingLibrary}
              selectedId={selectedId}
              onOpen={setSelectedId}
              onDelete={deletePaper}
            />
          </div>
          <div hidden={tab !== "upload"}>
            <UploadView onOpen={setSelectedId} onLibraryChanged={refreshLibrary} />
          </div>
        </div>

        {selectedId && (
          <aside className="min-w-0 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:self-start lg:overflow-y-auto">
            <PaperDetail key={selectedId} paperId={selectedId} onClose={() => setSelectedId(null)} />
          </aside>
        )}
      </main>
    </div>
  );
}
