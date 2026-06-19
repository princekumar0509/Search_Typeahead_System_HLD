import React, { useState } from "react";
import SearchBox from "./components/SearchBox";
import Trending from "./components/Trending";

/**
 * Application shell: title, search box and trending panel.
 * `query` lives here so trending clicks can populate the search box, and a
 * `refreshKey` bump re-mounts Trending after a submission to reflect new counts.
 */
export default function App() {
  const [query, setQuery] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="mx-auto flex min-h-full max-w-2xl flex-col px-4 py-12 sm:py-20">
      <header className="mb-8 text-center">
        <h1 className="text-3xl font-bold tracking-tight text-slate-800">
          🔎 Search Typeahead
        </h1>
        <p className="mt-2 text-sm text-slate-500">
          Prefix suggestions · popularity ranking · distributed cache
        </p>
      </header>

      <SearchBox
        query={query}
        setQuery={setQuery}
        onSubmitted={() => setRefreshKey((k) => k + 1)}
      />

      <Trending key={refreshKey} onPick={(q) => setQuery(q)} />

      <footer className="mt-auto pt-10 text-center text-xs text-slate-400">
        FastAPI · PostgreSQL · Consistent-hash distributed cache · Batch writes
      </footer>
    </div>
  );
}
