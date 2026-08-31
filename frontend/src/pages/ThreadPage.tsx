import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Download,
  ExternalLink,
  Loader2,
  ImageIcon,
  Images,
  User,
  Tag,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ImageOut } from "../api/client";
import { Lightbox } from "../components/Lightbox";
import Pagination from "../components/Pagination";
import { RetryImage } from "../components/RetryImage";

// The thread view paginates the full image list (across all posts) this many
// images per page. Post pagination is gone — the whole thread loads at once.
const IMAGES_PER_PAGE = 12;

// A loaded image annotated with its origin post and its position within the
// flattened list of the current post page. globalIndex lines up with the
// lightbox's navigation over pageImages.
type FlatItem = {
  img: ImageOut;
  postIndex: number;
  postId: number;
  globalIndex: number;
};

export default function ThreadPage() {
  const { threadId } = useParams<{ threadId: string }>();
  const tid = Number(threadId) || 0;
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const qc = useQueryClient();
  const downloadMut = useMutation({
    mutationFn: () => api.addToQueue([tid]),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });
  const [imagePage, setImagePage] = useState(1);
  const gridTopRef = useRef<HTMLDivElement>(null);

  // Return to the exact previous view (forum + page) when possible.
  const backTarget = (() => {
    const from = searchParams.get("from");
    const pg = searchParams.get("page");
    if (from) return `/forum/${from}${pg ? `?page=${pg}` : ""}`;
    return "/";
  })();
  const handleBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate(backTarget);
  };

  const { data: thread, isLoading, error, refetch } = useQuery({
    queryKey: ["thread", tid],
    queryFn: () => api.thread(tid),
    enabled: tid > 0,
  });

  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: api.config,
    staleTime: 5 * 60_000,
  });

  const hosts = useMemo(() => {
    if (!thread) return [];
    const s = new Set<string>();
    thread.images.forEach((img) => img.host && s.add(img.host));
    return [...s];
  }, [thread]);

  // Flatten the WHOLE thread's images (thread.images already holds every image
  // across all posts, each carrying its post_id) into one ordered list, tagging
  // each with its origin post so we can paginate IMAGES_PER_PAGE at a time while
  // still rendering per-post section headers. postIndex is derived from
  // first-appearance order of post_id. globalIndex == index in pageImages,
  // which the lightbox navigates across.
  const flat = useMemo<FlatItem[]>(() => {
    if (!thread) return [];
    const postOrder = new Map<number, number>();
    let nextIndex = 1;
    let gi = 0;
    const out: FlatItem[] = [];
    for (const img of thread.images) {
      let postIndex = postOrder.get(img.post_id);
      if (postIndex === undefined) {
        postIndex = nextIndex++;
        postOrder.set(img.post_id, postIndex);
      }
      out.push({ img, postIndex, postId: img.post_id, globalIndex: gi });
      gi++;
    }
    return out;
  }, [thread]);

  const pageImages: ImageOut[] = useMemo(() => flat.map((f) => f.img), [flat]);

  // Image-pagination bounds. imgPage is the clamped view of imagePage (guards
  // against it lagging one render behind a reset).
  const totalImages = flat.length;
  const imagePageCount = Math.max(1, Math.ceil(totalImages / IMAGES_PER_PAGE));
  const imgPage = Math.min(Math.max(1, imagePage), imagePageCount);
  const sliceStart = (imgPage - 1) * IMAGES_PER_PAGE;
  const currentSlice = flat.slice(sliceStart, sliceStart + IMAGES_PER_PAGE);

  // Group the current ≤IMAGES_PER_PAGE slice back into per-post sections so the
  // post division stays visible: consecutive images from the same post share
  // one header + grid.
  const postGroups: { postId: number; postIndex: number; items: FlatItem[] }[] = [];
  for (const item of currentSlice) {
    const last = postGroups[postGroups.length - 1];
    if (last && last.postId === item.postId) last.items.push(item);
    else postGroups.push({ postId: item.postId, postIndex: item.postIndex, items: [item] });
  }

  // Reset the image page when the thread changes.
  useEffect(() => {
    setImagePage(1);
  }, [tid]);

  const goToImagePage = (next: number) => {
    setImagePage(Math.min(Math.max(1, next), imagePageCount));
    gridTopRef.current?.scrollIntoView({ block: "start" });
  };

  if (isLoading) {
    return (
      <div className="flex h-[70vh] items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading photoset…
      </div>
    );
  }

  if (error || !thread) {
    return (
      <div className="flex h-[70vh] flex-col items-center justify-center text-muted-foreground">
        <p className="mb-1 text-sm">Failed to load photoset.</p>
        <p className="mb-4 text-xs opacity-60">{String(error)}</p>
        <div className="flex gap-3">
          <button
            onClick={() => refetch()}
            className="rounded-lg bg-primary/20 px-4 py-2 text-sm text-primary hover:bg-primary/30"
          >
            Retry
          </button>
          <Link
            to="/"
            className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-accent/20"
          >
            Go home
          </Link>
        </div>
      </div>
    );
  }


  return (
    <div className="pb-8">
      {/* Header */}
      <div className="mb-5">
        <div className="mb-3 flex items-center gap-3">
          <button
            onClick={handleBack}
            className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm transition hover:bg-accent/20"
          >
            <ArrowLeft className="h-4 w-4" /> Back
          </button>
          {thread.image_count > 0 && (
            <button
              onClick={() => downloadMut.mutate()}
              disabled={downloadMut.isPending}
              className="flex items-center gap-1.5 rounded-lg bg-primary/20 px-3 py-1.5 text-sm font-medium text-primary transition hover:bg-primary/30 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {downloadMut.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Adding…
                </>
              ) : (
                <>
                  <Download className="h-4 w-4" /> Download
                </>
              )}
            </button>
          )}
          {config?.forum_url && (
            <a
              href={`${config.forum_url}/threads/${tid}`}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm transition hover:bg-accent/20"
              title="Open this thread on the forum"
            >
              <ExternalLink className="h-4 w-4" /> Forum
            </a>
          )}
          {hosts.length > 0 && (
            <div className="flex items-center gap-1.5">
              {hosts.map((h) => (
                <span
                  key={h}
                  className="flex items-center gap-1 rounded-md bg-primary/15 px-2 py-1 text-xs font-medium text-primary"
                >
                  <Tag className="h-3 w-3" />
                  {h}
                </span>
              ))}
            </div>
          )}
        </div>

        <h1 className="mb-2 text-xl font-semibold leading-tight tracking-tight">
          {thread.title}
        </h1>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Images className="h-3.5 w-3.5" />
            {thread.image_count} images
          </span>
          {thread.post_count > 0 && (
            <span className="flex items-center gap-1">
              <ImageIcon className="h-3.5 w-3.5" />
              {thread.post_count} posts
            </span>
          )}
          {thread.forum_title && thread.forum_id > 0 && (
            <Link
              to={`/forum/${thread.forum_id}`}
              className="flex items-center gap-1 transition-colors hover:text-primary"
            >
              <ImageIcon className="h-3.5 w-3.5" />
              {thread.forum_title}
            </Link>
          )}
          {thread.author && (
            <span className="flex items-center gap-1">
              <User className="h-3.5 w-3.5" />
              {thread.author}
            </span>
          )}
        </div>
      </div>

      {/* Images */}
      <div className="space-y-6">
        <div ref={gridTopRef} />

        {/* Top pagination */}
        {imagePageCount > 1 && (
          <div className="space-y-1">
            <Pagination
              page={imgPage}
              totalPages={imagePageCount}
              onChange={goToImagePage}
            />
            <p className="text-center text-xs text-muted-foreground">
              Images {sliceStart + 1}–{sliceStart + currentSlice.length} of{" "}
              {totalImages}
            </p>
          </div>
        )}

        {postGroups.length === 0 ? (
          <p className="py-12 text-center text-sm text-muted-foreground">
            No images.
          </p>
        ) : (
          postGroups.map((group) => (
            <section key={group.postId}>
              <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                <span className="rounded bg-primary/15 px-2 py-0.5 text-primary">
                  Post {group.postIndex}
                </span>
                <span>
                  {group.items.length} image{group.items.length === 1 ? "" : "s"}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
                {group.items.map((item) => (
                  <div key={item.img.id} className="aspect-[3/4]">
                    <Thumb
                      img={item.img}
                      onClick={() => setLightboxIndex(item.globalIndex)}
                    />
                  </div>
                ))}
              </div>
            </section>
          ))
        )}

        {/* Bottom pagination */}
        {imagePageCount > 1 && (
          <div className="space-y-1 pt-2">
            <Pagination
              page={imgPage}
              totalPages={imagePageCount}
              onChange={goToImagePage}
            />
            <p className="text-center text-xs text-muted-foreground">
              Images {sliceStart + 1}–{sliceStart + currentSlice.length} of{" "}
              {totalImages}
            </p>
          </div>
        )}
      </div>

      {/* Lightbox */}
      {lightboxIndex !== null && pageImages.length > 0 && (
        <Lightbox
          images={pageImages}
          startIndex={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onNavigate={setLightboxIndex}
        />
      )}

    </div>
  );
}

function Thumb({
  img,
  onClick,
}: {
  img: ImageOut;
  onClick: () => void;
}) {
  const src = api.imageUrl(img.id, "medium");

  // Fills its parent cell — sizing (the aspect-[3/4] box) is the caller's
  // responsibility so this component stays layout-agnostic.
  return (
    <button
      onClick={onClick}
      className="group relative h-full w-full overflow-hidden rounded-lg border border-border bg-muted/20 transition hover:border-primary/50 hover:shadow-lg hover:shadow-primary/5"
    >
      {src ? (
        <RetryImage
          src={src}
          alt={`Image ${img.idx + 1}`}
          loading="lazy"
          decoding="async"
          className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
        />
      ) : (
        <div className="flex h-full items-center justify-center text-muted-foreground/30">
          <ImageIcon className="h-8 w-8" />
        </div>
      )}
      <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white opacity-0 backdrop-blur-sm transition group-hover:opacity-100">
        {img.idx + 1}
      </span>
    </button>
  );
}
