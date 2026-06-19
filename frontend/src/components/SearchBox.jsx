import React, { useEffect, useRef, useState } from "react";
import { useDebounce } from "../hooks/useDebounce";
import { fetchSuggestions, submitSearch } from "../api/client";
import SuggestionDropdown from "./SuggestionDropdown";

/**
 * The core search experience:
 *   - debounced suggestion fetching (300ms)
 *   - keyboard navigation (ArrowUp/Down, Enter, Escape)
 *   - loading + error states
 *   - submit button that POSTs to /search
 *
 * `query` is controlled from the parent so trending picks can fill the box.
 */
export default function SearchBox({ query, setQuery, onSubmitted }) {
  const debounced = useDebounce(query, 300);

  const [suggestions, setSuggestions] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [submitMsg, setSubmitMsg] = useState(null);

  // Skip the suggestion fetch that would fire immediately after we
  // programmatically set the query (selection / submit).
  const skipNextFetch = useRef(false);

  // --- debounced suggestion fetch -------------------------------------------
  useEffect(() => {
    if (skipNextFetch.current) {
      skipNextFetch.current = false;
      return;
    }
    const term = debounced.trim();
    if (!term) {
      setSuggestions([]);
      setMeta(null);
      setOpen(false);
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchSuggestions(term, controller.signal)
      .then((data) => {
        setSuggestions(data.suggestions || []);
        setMeta({ node: data.node, cache_hit: data.cache_hit });
        setOpen(true);
        setActiveIndex(-1);
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          setError("Could not load suggestions. Is the backend running?");
          setOpen(true);
        }
      })
      .finally(() => setLoading(false));

    return () => controller.abort();
  }, [debounced]);

  // --- actions --------------------------------------------------------------
  function choose(value) {
    skipNextFetch.current = true;
    setQuery(value);
    setOpen(false);
    setActiveIndex(-1);
  }

  async function handleSubmit(e) {
    e?.preventDefault();
    const term = query.trim();
    if (!term) return;
    setOpen(false);
    try {
      const res = await submitSearch(term);
      setSubmitMsg(res.message || "Searched");
      onSubmitted?.(term);
    } catch (err) {
      setSubmitMsg(`Error: ${err.message}`);
    } finally {
      setTimeout(() => setSubmitMsg(null), 2500);
    }
  }

  // --- keyboard navigation --------------------------------------------------
  function onKeyDown(e) {
    if (!open || suggestions.length === 0) {
      if (e.key === "Enter") handleSubmit(e);
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActiveIndex((i) => (i + 1) % suggestions.length);
        break;
      case "ArrowUp":
        e.preventDefault();
        setActiveIndex((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
        break;
      case "Enter":
        e.preventDefault();
        if (activeIndex >= 0) {
          choose(suggestions[activeIndex].query);
        } else {
          handleSubmit(e);
        }
        break;
      case "Escape":
        setOpen(false);
        setActiveIndex(-1);
        break;
      default:
        break;
    }
  }

  return (
    <form onSubmit={handleSubmit} className="relative w-full">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type="text"
            value={query}
            autoFocus
            placeholder="Search for anything…"
            aria-label="Search"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            onFocus={() => suggestions.length > 0 && setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 120)}
            className="w-full rounded-full border border-slate-300 bg-white px-5 py-3 text-base shadow-sm outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
          />
          {open && (
            <SuggestionDropdown
              suggestions={suggestions}
              loading={loading}
              error={error}
              activeIndex={activeIndex}
              onSelect={choose}
              meta={meta}
            />
          )}
        </div>
        <button
          type="submit"
          className="rounded-full bg-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 active:scale-95"
        >
          Search
        </button>
      </div>

      {submitMsg && (
        <div className="mt-2 text-center text-sm font-medium text-green-600">
          {submitMsg}
        </div>
      )}
    </form>
  );
}
