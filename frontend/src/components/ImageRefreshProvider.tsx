import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

/**
 * Lets the global "refresh failed images" button in the header reach every
 * currently-mounted `<RetryImage>` on the active page.
 *
 * Each `RetryImage` registers an accessor pair (read-failed-state + reload).
 * The provider keeps a live count of failed images so the button can show a
 * badge, and `refreshFailed()` calls `reload()` on every failed one.
 *
 * The registry is keyed by id (not by URL) because the same URL can appear in
 * several cards and each `<RetryImage>` instance has its own retry state.
 */
interface Entry {
  isFailed: () => boolean;
  reload: () => void;
}

export interface ImageRefreshApi {
  register: (entry: Entry) => number;
  unregister: (id: number) => void;
  reportChange: () => void;
  refreshFailed: () => number;
  failedCount: number;
}

const Ctx = createContext<ImageRefreshApi | null>(null);

export function useImageRefresh(): ImageRefreshApi | null {
  return useContext(Ctx);
}

export function ImageRefreshProvider({ children }: { children: ReactNode }) {
  const entries = useRef(new Map<number, Entry>());
  const nextId = useRef(1);
  const [failedCount, setFailedCount] = useState(0);

  const recount = useCallback(() => {
    let n = 0;
    entries.current.forEach((e) => {
      if (e.isFailed()) n++;
    });
    setFailedCount(n);
  }, []);

  const register = useCallback((entry: Entry) => {
    const id = nextId.current++;
    entries.current.set(id, entry);
    return id;
  }, []);

  const unregister = useCallback(
    (id: number) => {
      entries.current.delete(id);
      recount();
    },
    [recount],
  );

  const reportChange = useCallback(() => recount(), [recount]);

  const refreshFailed = useCallback(() => {
    let n = 0;
    entries.current.forEach((e) => {
      if (e.isFailed()) {
        e.reload();
        n++;
      }
    });
    return n;
  }, []);

  const value = useMemo<ImageRefreshApi>(
    () => ({ register, unregister, reportChange, refreshFailed, failedCount }),
    [register, unregister, reportChange, refreshFailed, failedCount],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
