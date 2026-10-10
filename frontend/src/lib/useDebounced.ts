import { useEffect, useState } from "react";

/** ``value`` once it has stopped changing for ``delayMs`` (for live checks while typing). */
export function useDebounced<T>(value: T, delayMs = 400): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => {
      setSettled(value);
    }, delayMs);
    return () => {
      window.clearTimeout(id);
    };
  }, [value, delayMs]);
  return settled;
}
