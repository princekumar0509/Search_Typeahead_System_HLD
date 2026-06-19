import { useEffect, useState } from "react";

/**
 * Return a debounced copy of `value` that only updates after `delay` ms of
 * no changes. Used to throttle typeahead API calls to one per 300ms pause.
 */
export function useDebounce(value, delay = 300) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);

  return debounced;
}
