import { useEffect, useRef, useState } from "react";
import { RotateCw, XCircle } from "lucide-react";
import { useImageRetry } from "../hooks/useImageRetry";
import { useImageRefresh } from "./ImageRefreshProvider";
import { VLoader } from "./VLoader";

interface RetryImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string;
  /** px size of the red ✕ fallback icon. */
  fallbackIconSize?: number;
  /** Show a reload button on hover (top-right). Default true. */
  showReloadButton?: boolean;
  /**
   * Play the brief brightness flash after a smooth same-image swap
   * (thumb→medium). Meaningful for unsolicited upgrades (wave loader on the
   * cover); noise when the user caused the swap (hover carousel previews).
   * Default true.
   */
  flashOnSwap?: boolean;
}

/**
 * Drop-in replacement for `<img>` that transparently retries a failed load
 * (cache-busted, up to 3× with 400ms backoff) and falls back to a red ✕ icon
 * instead of the browser's native broken-image glyph.
 *
 * A small reload button appears on hover (top-right) that forcibly re-fetches
 * the image — useful when the auto-retry gave up but the user wants to try
 * again (e.g. after a flaky network recovers). It also shows on the red ✕
 * fallback so a failed image can be retried.
 *
 * `className` is applied to the wrapper element (which wraps the `<img>` /
 * fallback), so positioning / sizing / opacity classes behave identically
 * either way — useful for stacked previews toggled via opacity.
 */
export function RetryImage({
  src,
  alt = "",
  className,
  fallbackIconSize = 28,
  showReloadButton = true,
  flashOnSwap = true,
  onError,
  onLoad,
  ...rest
}: RetryImageProps) {
  const main = useImageRetry(src);
  const [spinning, setSpinning] = useState(false);

  // Red ✕ only when there is truly nothing to show (no src or load failed).
  const showCross = !src || main.failed;

  // Register with the global image-refresh registry so the header "refresh"
  // button can reload this image when it is in the failed state. A ref holds
  // the latest {failed, reload} snapshot so the registered accessors always
  // read fresh values without re-registering on every render.
  const refreshApi = useImageRefresh();
  const stateRef = useRef({ failed: false, reload: () => {} });
  stateRef.current = {
    failed: showCross,
    reload: () => main.reload(),
  };

  useEffect(() => {
    if (!refreshApi) return;
    const id = refreshApi.register({
      isFailed: () => stateRef.current.failed,
      reload: () => stateRef.current.reload(),
    });
    refreshApi.reportChange();
    return () => {
      refreshApi.unregister(id);
    };
  }, [refreshApi]);

  // Re-report whenever the failed state flips so the badge count stays live.
  useEffect(() => {
    refreshApi?.reportChange();
  }, [refreshApi, showCross]);

  const handleReload = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setSpinning(true);
    main.reload();
    // Stop the spin after a cap so it never spins forever if neither event
    // fires (e.g. the request hangs again).
    window.setTimeout(() => setSpinning(false), 12_000);
  };

  const reloadButton = showReloadButton && src && (
    <button
      type="button"
      onClick={handleReload}
      title="Перезагрузить изображение"
      className="absolute right-1 top-1 z-10 flex h-7 w-7 items-center justify-center rounded-md bg-black/60 text-white opacity-0 backdrop-blur-sm transition-opacity hover:bg-black/80 group-hover/retry:opacity-100"
    >
      <RotateCw className={`h-4 w-4 ${spinning ? "animate-spin" : ""}`} />
    </button>
  );

  // If the caller already supplied a position utility (absolute/relative/fixed/
  // sticky), don't override it — stacking overlays rely on ``absolute`` to
  // layer multiple RetryImages on top of each other with opacity controlling
  // visibility.  Tailwind's compiled CSS orders ``.relative`` after
  // ``.absolute``, so hardcoding ``relative`` here would silently win and
  // break callers that pass ``absolute`` via className.
  const positionClass =
    className && /\b(absolute|relative|fixed|sticky)\b/.test(className)
      ? ""
      : "relative";

  // Forward the caller's object-fit to the inner <img> (className is applied to
  // the wrapper div, so without this the hardcoded object-cover below always
  // wins). Default to object-cover to preserve existing behaviour elsewhere.
  const objectFitClass =
    (className &&
      className.match(/\bobject-(contain|cover|fill|none|scale-down)\b/)?.[0]) ||
    "object-cover";

  if (showCross) {
    return (
      <div className={`group/retry ${positionClass} overflow-hidden ${className ?? ""}`}>
        <XCircle
          style={{ width: fallbackIconSize, height: fallbackIconSize }}
          className="absolute inset-0 m-auto text-red-500/70"
        />
        {reloadButton}
      </div>
    );
  }

  return (
    <div className={`group/retry ${positionClass} overflow-hidden ${className ?? ""}`}>
      <img
        src={main.src}
        alt={alt}
        onError={(e) => {
          main.onError();
          setSpinning(false);
          onError?.(e);
        }}
        onLoad={(e) => {
          main.onLoad();
          setSpinning(false);
          onLoad?.(e);
        }}
        className={`h-full w-full ${objectFitClass} ${main.loaded ? "opacity-100" : "opacity-0"} ${main.swapped && flashOnSwap ? "img-swap-flash" : ""}`}
        {...rest}
      />
      {!main.loaded && (
        <div className="absolute inset-0 flex items-center justify-center bg-muted/20">
          <VLoader size={36} />
        </div>
      )}
      {reloadButton}
    </div>
  );
}
