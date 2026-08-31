import { useCallback, useEffect, useRef, useState } from "react";
import {
  X,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Download,
  Maximize2,
  Play,
  Pause,
  RotateCw,
} from "lucide-react";
import { api, ImageOut } from "../api/client";
import { cn } from "../lib/utils";
import { useImageRetry } from "../hooks/useImageRetry";
import { VLoader } from "./VLoader";

interface LightboxProps {
  images: ImageOut[];
  startIndex: number;
  onClose: () => void;
  onNavigate?: (index: number) => void;
}

// Preloading neighbours pulls full-size originals (5-20 MB each). Skip it when
// the user is on a metered/slow connection — they'd pay real money or wait
// real time for bytes they may never see. Computed once per session.
const conn = typeof navigator !== "undefined"
  ? (navigator as Navigator & {
      connection?: { saveData?: boolean; effectiveType?: string };
    }).connection
  : undefined;
const PRELOAD_NEIGHBOURS = !(
  conn?.saveData || /(^|\b)(2g)($|\b)/.test(conn?.effectiveType || "")
);

export function Lightbox({ images, startIndex, onClose, onNavigate }: LightboxProps) {
  const [index, setIndex] = useState(startIndex);
  const [isLoading, setIsLoading] = useState(true);
  // zoom = 1.0 → image fits the viewport; larger values zoom in, capped so the
  // image never exceeds its native (1:1) resolution (no fake upscaling).
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [uiHidden, setUiHidden] = useState(false);
  const [slideshow, setSlideshow] = useState(false);
  const [slideInterval, setSlideInterval] = useState(3);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [containerSize, setContainerSize] = useState({ w: 0, h: 0 });
  const containerRef = useRef<HTMLDivElement | null>(null);
  const touchStartX = useRef<number | null>(null);
  const dragRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number; moved: boolean } | null>(null);
  const wheelLock = useRef(false);

  const current = images[index];
  const total = images.length;

  // Fit scale: how much the native image is shrunk to fit the viewport, capped
  // at 1 so a small image is never enlarged beyond its real pixels.
  const fitScale =
    natural && containerSize.w && containerSize.h
      ? Math.min(containerSize.w / natural.w, containerSize.h / natural.h, 1)
      : 1;
  // Max zoom reaches exactly 1:1 with the source pixels.
  const maxZoom = fitScale > 0 ? 1 / fitScale : 1;
  const isZoomed = zoom > 1.0001;

  // Keep the image edges within view while panning.
  const clampPan = useCallback(
    (x: number, y: number, z: number) => {
      if (!natural || !containerSize.w) return { x: 0, y: 0 };
      const overX = Math.max(0, (natural.w * fitScale * z - containerSize.w) / 2);
      const overY = Math.max(0, (natural.h * fitScale * z - containerSize.h) / 2);
      return { x: Math.max(-overX, Math.min(overX, x)), y: Math.max(-overY, Math.min(overY, y)) };
    },
    [natural, containerSize, fitScale],
  );

  const goTo = useCallback(
    (i: number) => {
      const clamped = Math.max(0, Math.min(total - 1, i));
      if (clamped === index) return;
      setIndex(clamped);
      onNavigate?.(clamped);
    },
    [index, total, onNavigate],
  );

  const prev = useCallback(() => goTo(index - 1), [goTo, index]);
  const next = useCallback(() => goTo(index + 1), [goTo, index]);

  const toggleZoom = useCallback(() => {
    setPan({ x: 0, y: 0 });
    setZoom((z) => (z > 1 ? 1 : maxZoom));
  }, [maxZoom]);

  // Pan handlers (only active when zoomed in)
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (!isZoomed) return;
      e.preventDefault();
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        baseX: pan.x,
        baseY: pan.y,
        moved: false,
      };
    },
    [isZoomed, pan.x, pan.y],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      const d = dragRef.current;
      if (!d) return;
      const dx = e.clientX - d.startX;
      const dy = e.clientY - d.startY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) d.moved = true;
      setPan(clampPan(d.baseX + dx, d.baseY + dy, zoom));
    },
    [clampPan, zoom],
  );

  const handleMouseUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  const handleDoubleClick = useCallback(() => {
    toggleZoom();
  }, [toggleZoom]);

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      switch (e.key) {
        case "ArrowLeft":
          e.preventDefault();
          prev();
          break;
        case "ArrowRight":
          e.preventDefault();
          next();
          break;
        case "Escape":
          e.preventDefault();
          if (uiHidden) {
            setUiHidden(false);
          } else {
            onClose();
          }
          break;
        case "Home":
          e.preventDefault();
          goTo(0);
          break;
        case "End":
          e.preventDefault();
          goTo(total - 1);
          break;
        case "f":
        case "F":
          e.preventDefault();
          setUiHidden((h) => !h);
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [prev, next, goTo, onClose, total, uiHidden]);

  // Mouse wheel: zoom in/out while zoomed; otherwise navigate between images.
  useEffect(() => {
    const handler = (e: WheelEvent) => {
      if (isZoomed) {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.2 : 1 / 1.2;
        const nz = Math.max(1, Math.min(maxZoom, zoom * factor));
        if (nz === zoom) return;
        setZoom(nz);
        if (nz <= 1) setPan({ x: 0, y: 0 });
        else setPan((p) => clampPan(p.x, p.y, nz));
        return;
      }
      if (wheelLock.current) return;
      if (Math.abs(e.deltaY) < 10) return;
      wheelLock.current = true;
      if (e.deltaY > 0) {
        next();
      } else {
        prev();
      }
      setTimeout(() => { wheelLock.current = false; }, 250);
    };
    window.addEventListener("wheel", handler, { passive: false });
    return () => window.removeEventListener("wheel", handler);
  }, [isZoomed, zoom, maxZoom, next, prev, clampPan]);

  // Lock body scroll while open
  useEffect(() => {
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, []);

  // Reset loading/zoom/pan state when the current image changes
  useEffect(() => {
    setIsLoading(true);
    setNatural(null);
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, [index]);

  // Preload the neighbouring full images so ←/→ navigation feels instant
  // instead of starting a fresh fetch on every step. The browser dedupes
  // against the immutable (1-year) image cache, so this is a no-op when the
  // image was already fetched for the grid or a previous visit.
  useEffect(() => {
    if (!PRELOAD_NEIGHBOURS) return;
    for (const i of [index - 1, index + 1]) {
      if (i >= 0 && i < total) {
        const pre = new Image();
        pre.src = api.imageUrl(images[i].id, "full");
      }
    }
  }, [index, total, images]);

  // Slideshow: auto-advance every N seconds, looping back to the first image.
  useEffect(() => {
    if (!slideshow) return;
    const id = window.setInterval(() => {
      setIndex((i) => {
        const ni = i + 1 >= total ? 0 : i + 1;
        onNavigate?.(ni);
        return ni;
      });
    }, slideInterval * 1000);
    return () => window.clearInterval(id);
  }, [slideshow, slideInterval, total, onNavigate]);

  // Track the image container size so the zoom math knows the viewport.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setContainerSize({ w: el.clientWidth, h: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [current?.id]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
  }, []);

  const handleTouchEnd = useCallback(
    (e: React.TouchEvent) => {
      if (touchStartX.current === null) return;
      const dx = e.changedTouches[0].clientX - touchStartX.current;
      if (Math.abs(dx) > 50) {
        if (dx > 0) prev();
        else next();
      }
      touchStartX.current = null;
    },
    [prev, next],
  );

  const fullUrl = current ? api.imageUrl(current.id, "full") : "";
  const { src: imgSrc, failed: imgFailed, onError: onImgError, onLoad: onImgLoad, reload } =
    useImageRetry(fullUrl);

  const downloadName = current
    ? `image-${String(current.idx + 1).padStart(3, "0")}.${(() => {
        const m = (current.thumb_url || current.main_url).match(
          /\.(jpg|jpeg|png|gif|webp|bmp)$/i,
        );
        return m ? m[1].toLowerCase() : "jpg";
      })()}`
    : "";

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-black/95 backdrop-blur-sm"
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      {/* Top bar */}
      {!uiHidden && (
        <div className="flex items-center justify-between px-4 py-3 text-white/80">
          <span className="text-sm font-medium tabular-nums">
            {index + 1} <span className="text-white/40">/ {total}</span>
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={toggleZoom}
              disabled={maxZoom <= 1}
              className="rounded-lg p-2 text-white/70 transition hover:bg-white/10 hover:text-white disabled:opacity-30"
              title={isZoomed ? "Zoom out (fit to screen)" : "Zoom in (to 1:1)"}
            >
              {isZoomed ? <ZoomOut className="h-5 w-5" /> : <ZoomIn className="h-5 w-5" />}
            </button>
            <button
              onClick={() => setSlideshow((s) => !s)}
              className="rounded-lg p-2 text-white/70 transition hover:bg-white/10 hover:text-white"
              title={slideshow ? "Stop slideshow" : "Start slideshow"}
            >
              {slideshow ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5" />}
            </button>
            <button
              onClick={() => setUiHidden((h) => !h)}
              className="rounded-lg p-2 text-white/70 transition hover:bg-white/10 hover:text-white"
              title={uiHidden ? "Show UI" : "Hide UI (F)"}
            >
              <Maximize2 className="h-5 w-5" />
            </button>
            {current && (
              <a
                href={fullUrl}
                download={downloadName}
                target="_blank"
                rel="noreferrer"
                className="rounded-lg p-2 text-white/70 transition hover:bg-white/10 hover:text-white"
                title="Download image"
              >
                <Download className="h-5 w-5" />
              </a>
            )}
            <button
              onClick={onClose}
              className="rounded-lg p-2 text-white/70 transition hover:bg-white/10 hover:text-white"
              title="Close (Esc)"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>
      )}

      {/* Image area */}
      <div
        className="relative flex flex-1 items-center justify-center overflow-hidden px-4 pb-4"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        {/* Nav left */}
        {index > 0 && !uiHidden && (
          <button
            onClick={prev}
            className="absolute left-2 top-1/2 z-10 -translate-y-1/2 rounded-full bg-white/10 p-2.5 text-white transition hover:bg-white/20"
            title="Previous (←)"
          >
            <ChevronLeft className="h-6 w-6" />
          </button>
        )}

        {/* Nav right */}
        {index < total - 1 && !uiHidden && (
          <button
            onClick={next}
            className="absolute right-2 top-1/2 z-10 -translate-y-1/2 rounded-full bg-white/10 p-2.5 text-white transition hover:bg-white/20"
            title="Next (→)"
          >
            <ChevronRight className="h-6 w-6" />
          </button>
        )}

        {/* Loading indicator */}
        {isLoading && !imgFailed && (
          <div className="absolute inset-0 flex items-center justify-center">
            <VLoader size={48} />
          </div>
        )}

        {/* Error */}
        {imgFailed ? (
          <div className="flex flex-col items-center gap-2 text-white/50">
            <X className="h-10 w-10 opacity-50" />
            <p className="text-sm">Failed to load image</p>
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setIsLoading(true);
                reload();
              }}
              className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-xs text-white/80 transition hover:bg-white/20 hover:text-white"
              title="Перезагрузить изображение"
            >
              <RotateCw className="h-3.5 w-3.5" />
              Перезагрузить
            </button>
            <a
              href={current?.main_url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-primary hover:underline"
            >
              Open original
            </a>
          </div>
        ) : current ? (
          <div
            ref={containerRef}
            onClick={(e) => {
              if (e.target === e.currentTarget) onClose();
            }}
            className="group/reload relative flex h-full w-full items-center justify-center"
          >
            <img
              key={current.id}
              src={imgSrc}
              alt={`Image ${index + 1}`}
              className={cn(
                "select-none object-contain transition-opacity duration-300 will-change-transform",
                "max-h-full max-w-full",
                isLoading && "opacity-0",
                !isLoading && "opacity-100",
                isZoomed ? (dragRef.current ? "cursor-grabbing" : "cursor-grab") : "cursor-zoom-in",
              )}
              style={{
                transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                transformOrigin: "center center",
              }}
              onLoad={(e) => {
                const img = e.currentTarget;
                if (img.naturalWidth && img.naturalHeight) {
                  setNatural({ w: img.naturalWidth, h: img.naturalHeight });
                }
                onImgLoad();
                setIsLoading(false);
              }}
              onError={onImgError}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              onDoubleClick={handleDoubleClick}
              draggable={false}
            />
            {!isZoomed && !uiHidden && (
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setIsLoading(true);
                  reload();
                }}
                title="Перезагрузить изображение"
                className="absolute right-3 top-3 z-10 flex h-8 w-8 items-center justify-center rounded-md bg-black/60 text-white opacity-0 backdrop-blur-sm transition-opacity hover:bg-black/80 group-hover/reload:opacity-100"
              >
                <RotateCw className="h-4 w-4" />
              </button>
            )}
          </div>
        ) : null}
      </div>

      {/* Bottom info bar */}
      {current && !uiHidden && (
        <div className="flex items-center justify-between px-4 py-2.5 text-xs text-white/50">
          <div className="flex items-center gap-3">
            {current.host && (
              <span className="rounded bg-white/10 px-2 py-0.5 font-medium text-white/70">
                {current.host}
              </span>
            )}
            <span>
              Image #{current.idx + 1}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={prev}
              disabled={index === 0}
              className="transition hover:text-white disabled:opacity-30"
            >
              Prev
            </button>
            {slideshow && (
              <label className="flex items-center gap-1.5">
                <span className="tabular-nums">{slideInterval}s</span>
                <input
                  type="range"
                  min={1}
                  max={5}
                  step={1}
                  value={slideInterval}
                  onChange={(e) => setSlideInterval(Number(e.target.value))}
                  className="h-1 w-24 cursor-pointer accent-primary"
                />
              </label>
            )}
            <button
              onClick={next}
              disabled={index >= total - 1}
              className="transition hover:text-white disabled:opacity-30"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
