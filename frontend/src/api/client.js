// Thin API client for the typeahead backend.
// All calls go through the relative "/api" prefix, which Vite (dev) and nginx
// (prod) proxy to the FastAPI service.

const BASE = "/api";

/** Wrap fetch with JSON parsing, abort support and uniform error handling. */
async function request(path, { signal, method = "GET", body } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    signal,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Request failed (${res.status}): ${detail || res.statusText}`);
  }
  return res.json();
}

/** GET /suggest?q=<prefix> */
export function fetchSuggestions(prefix, signal) {
  const q = encodeURIComponent(prefix);
  return request(`/suggest?q=${q}`, { signal });
}

/** POST /search */
export function submitSearch(query) {
  return request(`/search`, { method: "POST", body: { query } });
}

/** GET /trending?mode=<mode> */
export function fetchTrending(mode = "popularity", signal) {
  return request(`/trending?mode=${encodeURIComponent(mode)}`, { signal });
}
