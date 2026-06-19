import React from "react";

/**
 * Renders the suggestion list under the search box.
 *
 * Handles three display states driven by props:
 *   - loading  -> skeleton row
 *   - error    -> error message
 *   - results  -> selectable, keyboard-highlightable rows
 */
export default function SuggestionDropdown({
  suggestions,
  loading,
  error,
  activeIndex,
  onSelect,
  meta,
}) {
  return (
    <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg animate-fade-in">
      {loading && (
        <div className="flex items-center gap-2 px-4 py-3 text-sm text-slate-500">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600" />
          Loading suggestions…
        </div>
      )}

      {!loading && error && (
        <div className="px-4 py-3 text-sm text-red-600">⚠ {error}</div>
      )}

      {!loading && !error && suggestions.length === 0 && (
        <div className="px-4 py-3 text-sm text-slate-400">No suggestions</div>
      )}

      {!loading &&
        !error &&
        suggestions.map((s, i) => (
          <button
            key={s.query}
            type="button"
            // Prevent input blur before the click registers.
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => onSelect(s.query)}
            className={`flex w-full items-center justify-between px-4 py-2.5 text-left text-sm transition-colors ${
              i === activeIndex ? "bg-blue-50 text-blue-700" : "hover:bg-slate-50"
            }`}
          >
            <span className="flex items-center gap-2">
              <svg className="h-4 w-4 text-slate-400" viewBox="0 0 20 20" fill="currentColor">
                <path
                  fillRule="evenodd"
                  d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.817-4.817A6 6 0 012 8z"
                  clipRule="evenodd"
                />
              </svg>
              {s.query}
            </span>
            <span className="text-xs tabular-nums text-slate-400">
              {Intl.NumberFormat().format(s.count)}
            </span>
          </button>
        ))}

      {meta && !loading && !error && (
        <div className="border-t border-slate-100 px-4 py-1.5 text-[11px] text-slate-400">
          node: <span className="font-medium">{meta.node}</span> ·{" "}
          {meta.cache_hit ? "cache hit" : "cache miss"}
        </div>
      )}
    </div>
  );
}
