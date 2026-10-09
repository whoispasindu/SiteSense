import { useEffect, useState } from "react";

export type ThemePreference = "system" | "light" | "dark";

const STORAGE_KEY = "sitesense-theme";
/** Null where matchMedia is missing (old browsers, test DOMs): then "system" means light. */
const media = (): MediaQueryList | null =>
  typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: dark)") : null;

export function readPreference(): ThemePreference {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(preference: ThemePreference): void {
  const dark = preference === "dark" || (preference === "system" && media()?.matches === true);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
}

/** The viewer's theme choice: a per-browser convenience, so local storage is the right place. */
export function useTheme(): [ThemePreference, (next: ThemePreference) => void] {
  const [preference, setPreference] = useState<ThemePreference>(readPreference);

  useEffect(() => {
    applyTheme(preference);
    if (preference !== "system") return;
    const query = media();
    if (!query) return;
    const follow = () => {
      applyTheme("system");
    };
    query.addEventListener("change", follow);
    return () => {
      query.removeEventListener("change", follow);
    };
  }, [preference]);

  const update = (next: ThemePreference) => {
    try {
      if (next === "system") localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* storage blocked: the choice lasts for this page view */
    }
    setPreference(next);
  };

  return [preference, update];
}
