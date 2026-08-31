import { useCallback, useState } from "react";

export type ViewMode = "grid" | "list";

const KEY = "viper.viewMode";

function read(): ViewMode {
  try {
    return localStorage.getItem(KEY) === "list" ? "list" : "grid";
  } catch {
    return "grid";
  }
}

/**
 * Global, session-persistent view mode (grid / list). Backed by localStorage
 * so the choice carries across pages (category ↔ search) and reloads. Each
 * page reads the current value on mount, so navigating between routes always
 * reflects the latest selection.
 */
export function useViewMode(): [ViewMode, (m: ViewMode) => void] {
  const [mode, setMode] = useState<ViewMode>(read);

  const set = useCallback((m: ViewMode) => {
    setMode(m);
    try {
      localStorage.setItem(KEY, m);
    } catch {
      /* ignore */
    }
  }, []);

  return [mode, set];
}
