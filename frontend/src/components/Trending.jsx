import React, { useEffect, useState } from "react";
import { fetchTrending } from "../api/client";

/**
 * Trending searches panel with a toggle between the two ranking modes:
 *   - popularity (score = count)
 *   - recency    (score = count + recent_count * 10)
 */
export default function Trending({ onPick }) {
  const [mode, setMode] = useState("popularity");
  const [items, setItems] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchTrending(mode, controller.signal)
      .then((data) => setItems(data.items || []))
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [mode]);

  return (
    <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          🔥 Trending searches
        </h2>
        <div className="inline-flex rounded-lg bg-slate-100 p-0.5 text-xs">
          {["popularity", "recency"].map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`rounded-md px-2.5 py-1 capitalize transition-colors ${
                mode === m ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {loading && <p className="text-sm text-slate-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">⚠ {error}</p>}

      <ol className="space-y-1">
        {items.map((item, idx) => (
          <li key={item.query}>
            <button
              onClick={() => onPick?.(item.query)}
              className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-50"
            >
              <span className="w-5 text-right font-semibold text-slate-400 tabular-nums">
                {idx + 1}
              </span>
              <span className="flex-1 truncate">{item.query}</span>
              <span className="text-xs text-slate-400 tabular-nums">
                {Intl.NumberFormat().format(item.score)}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
