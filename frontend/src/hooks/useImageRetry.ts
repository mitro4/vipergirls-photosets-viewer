import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Transparently retry a failed image load up to `maxRetries` times, then give
 * up and report failure so the caller can render a fallback.
 *
 * - A short backoff (`400ms`) separates attempts so transient errors (502,
 *   host hiccup) have time to clear.
 * - A cache-busting `_r=<n>` query param is appended on each retry so the
 *   browser issues a fresh request instead of reusing the failed one. The
 *   backend ignores this param (only `size` is parsed).
 *
 * No load-timeout: the backend's circuit breaker fast-fails dead hosts (502
 * → onError), and its own httpx timeouts (8–15s) guarantee the browser
 * always gets a response once a request starts. The browser's HTTP/1.1
 * 6-connection queue means many images wait their turn — a client-side
 * timeout would fire while they're still queued (before any network
 * activity), producing false red-✕s. onLoad/onError always fire eventually,
 * so we just wait.
 *
 * Returns the `src` to set on the `<img>` (empty string once exhausted), a
 * `failed` flag, `onError`/`onLoad` handlers to attach to the `<img>`, and a
 * `reload()` function to forcibly re-attempt a failed/hung image (resets
 * state and bumps the cache-bust token so the browser issues a fresh
 * request).
 */
export function useImageRetry(
  src: string,
  maxRetries = 3,
) {
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  // True briefly after a smooth swap (thumb→medium) finishes loading,
  // so the caller can play a subtle flash animation.
  const [swapped, setSwapped] = useState(false);
  // Tracks whether a src change happened while the image was already loaded
  // (i.e. an upgrade/swap rather than an initial load).
  const pendingSwap = useRef(false);
  // Extra cache-bust segment bumped by `reload()` so a forced retry issues a
  // brand-new request even after the auto-retry counter is exhausted.
  const [reloadToken, setReloadToken] = useState(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const swapTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Reset retry state when the underlying URL changes. NOTE: we deliberately
  // keep `loaded=true` if already loaded — this enables smooth thumb→medium
  // swaps: the browser keeps showing the (cached) thumb while the new medium
  // src loads in the background, then atomically swaps once it's ready.
  // Resetting `loaded=false` here would cause a white flash between swaps.
  useEffect(() => {
    if (loaded) pendingSwap.current = true;
    setAttempt(0);
    setFailed(false);
  }, [src]);

  useEffect(
    () => () => {
      clearTimeout(retryTimer.current);
      clearTimeout(swapTimer.current);
    },
    [],
  );

  const scheduleRetry = useCallback(() => {
    clearTimeout(retryTimer.current);
    retryTimer.current = setTimeout(
      () => {
        setAttempt((a) => {
          const next = a + 1;
          if (next > maxRetries) {
            setFailed(true);
            return a;
          }
          return next;
        });
      },
      400,
    );
  }, [maxRetries]);

  const onError = useCallback(() => scheduleRetry(), [scheduleRetry]);
  const onLoad = useCallback(() => {
    setLoaded(true);
    if (pendingSwap.current) {
      pendingSwap.current = false;
      setSwapped(true);
      clearTimeout(swapTimer.current);
      swapTimer.current = setTimeout(() => setSwapped(false), 600);
    }
  }, []);

  // Force a fresh fetch: clear timers, reset state, bump the cache-bust token.
  const reload = useCallback(() => {
    clearTimeout(retryTimer.current);
    pendingSwap.current = false;
    setFailed(false);
    setLoaded(false);
    setAttempt(0);
    setReloadToken((t) => t + 1);
  }, []);

  const actualSrc =
    failed || !src
      ? ""
      : (() => {
          const parts: string[] = [];
          if (attempt > 0) parts.push(`_r=${attempt}`);
          if (reloadToken > 0) parts.push(`_rr=${reloadToken}`);
          if (parts.length === 0) return src;
          return `${src}${src.includes("?") ? "&" : "?"}${parts.join("&")}`;
        })();

  return { src: actualSrc, failed, loaded, swapped, onError, onLoad, reload };
}
