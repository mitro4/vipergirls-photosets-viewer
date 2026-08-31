import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { matchPath, Outlet, useLocation } from "react-router-dom";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, FolderOpen, Heart, ListVideo, Menu, RotateCw, Search } from "lucide-react";
import { api } from "./api/client";
import { ImageRefreshProvider, useImageRefresh } from "./components/ImageRefreshProvider";
import DownloadQueuePanel from "./components/DownloadQueuePanel";
import { LoginModal } from "./components/LoginModal";
import { SearchPanel } from "./components/SearchPanel";
import { SettingsModal } from "./components/SettingsModal";
import { Sidebar } from "./components/Sidebar";
import CategoryPage from "./pages/CategoryPage";

const HIDDEN_CATEGORIES = new Set([
  "Adult Games",
  "Adult Stories",
  "Adult Video Feed",
]);

function loadSidebarOpen(): boolean {
  try {
    return localStorage.getItem("viper.sidebarOpen") !== "0";
  } catch {
    return true;
  }
}

export default function App() {
  const { data: groups } = useQuery({
    queryKey: ["categories"],
    queryFn: api.categories,
  });

  // Prefetch settings on app load so the Settings modal renders instantly
  // even while a thread's image streams saturate the browser's
  // 6-connection-per-host limit (HTTP/1.1 head-of-line blocking).  TanStack
  // Query dedupes this with the modal's own useQuery(["settings"]) — the
  // modal finds cached data (isLoading=false) and shows content immediately.
  useQuery({ queryKey: ["settings"], queryFn: api.settings });
  useQuery({ queryKey: ["stats"], queryFn: api.stats });

  // Download queue — poll only while work is in flight (queued/downloading).
  // Adding/stopping/starting invalidates ["queue"], which restarts polling.
  const { data: queueData } = useQuery({
    queryKey: ["queue"],
    queryFn: api.listQueue,
    refetchInterval: (query) =>
      query.state.data?.items.some(
        (it) => it.status === "downloading" || it.status === "queued",
      )
        ? 1000
        : false,
  });
  const queueActiveCount =
    queueData?.items.filter(
      (it) => it.status === "downloading" || it.status === "queued",
    ).length ?? 0;

  const [loginOpen, setLoginOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(loadSidebarOpen);

  const toggleSidebar = useCallback(() => {
    setSidebarOpen((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("viper.sidebarOpen", next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const visibleGroups = (groups ?? [])
    .map((g) => ({
      ...g,
      categories: g.categories.filter((c) => !HIDDEN_CATEGORIES.has(c.title)),
    }))
    .filter((g) => g.categories.length > 0);

  // --- DOM-level keep-alive for CategoryPage ---
  // The category routes ("/" and "/forum/:forumId") are NOT in the router's
  // child routes (see main.tsx). Instead we detect them via the URL and render
  // <CategoryPage> directly, always mounted. When the user navigates to a
  // thread, CategoryPage is hidden via CSS but stays mounted — so going back
  // is instant (no image reload, no crossfade replay, scroll preserved).
  // Outlet only renders for /thread/* and /search.
  const location = useLocation();
  const forumMatch = matchPath("/forum/:forumId", location.pathname);
  const isIndex = location.pathname === "/";
  const isOnCategory = isIndex || !!forumMatch;

  // The forum ID for the CURRENT URL, or null when on a non-category route.
  const currentForumId = forumMatch
    ? Number(forumMatch.params.forumId)
    : isIndex
      ? 0
      : null;
  // Last-visited forum — kept across thread navigation so the hidden
  // CategoryPage keeps rendering its previous state.
  const [cachedForumId, setCachedForumId] = useState<number>(0);
  useEffect(() => {
    if (currentForumId !== null) {
      setCachedForumId(currentForumId);
    }
  }, [currentForumId]);
  const renderedForumId = currentForumId ?? cachedForumId;

  const navigate = useNavigate();
  const qc = useQueryClient();

  return (
    <ImageRefreshProvider>
      <div className="flex h-screen w-screen overflow-hidden">
        <Sidebar
          groups={visibleGroups}
          onLoginClick={() => setLoginOpen(true)}
          onSettingsClick={() => setSettingsOpen(true)}
          collapsed={!sidebarOpen}
        />
        <main className="flex flex-1 flex-col overflow-hidden">
          <header className="flex shrink-0 items-center gap-4 border-b border-border px-6 py-3">
            <button
              onClick={toggleSidebar}
              title="Toggle sidebar"
              className="flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <Menu className="h-4 w-4" />
            </button>
            <button
              onClick={() => navigate(-1)}
              title="Back"
              className="flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <ArrowLeft className="h-4 w-4" />
            </button>
            <div className="ml-auto flex items-center gap-2">
              <RefreshButton />
              <div className="relative">
                <button
                  onClick={() => setQueueOpen((v) => !v)}
                  title="Download queue"
                  className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                >
                  <ListVideo className="h-4 w-4" />
                  Queue
                  {queueActiveCount > 0 && (
                    <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold text-primary-foreground">
                      {queueActiveCount}
                    </span>
                  )}
                </button>
                {queueOpen && (
                  <DownloadQueuePanel onClose={() => setQueueOpen(false)} />
                )}
              </div>
              <button
                onClick={() => navigate("/liked")}
                title="Liked photosets"
                className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              >
                <Heart className="h-4 w-4" />
                Liked
              </button>
              <button
                onClick={() => {
                  qc.invalidateQueries({ queryKey: ["downloads"] });
                  navigate("/downloads");
                }}
                title="Downloaded photosets"
                className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              >
                <FolderOpen className="h-4 w-4" />
                Downloads
              </button>
              <button
                onClick={() => setSearchOpen(true)}
                className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              >
                <Search className="h-4 w-4" />
                Search
              </button>
            </div>
          </header>
          {/* Both views stay mounted; visibility toggled via CSS. Each has its
              own scroll container so scroll positions survive independently. */}
          <div className="flex-1 overflow-hidden">
            <div
              className={
                isOnCategory
                  ? "h-full overflow-y-auto"
                  : "hidden h-full overflow-y-auto"
              }
            >
              <div className="mx-auto max-w-[1600px] p-6">
                <CategoryPage
                  forumId={renderedForumId}
                  active={isOnCategory}
                />
              </div>
            </div>
            <div className={isOnCategory ? "hidden h-full overflow-y-auto" : "h-full overflow-y-auto"}>
              <div className="mx-auto max-w-[1600px] p-6">
                <Outlet />
              </div>
            </div>
          </div>
        </main>
        {loginOpen && <LoginModal onClose={() => setLoginOpen(false)} />}
        {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
        {searchOpen && <SearchPanel onClose={() => setSearchOpen(false)} />}
      </div>
    </ImageRefreshProvider>
  );
}

function RefreshButton() {
  const api = useImageRefresh();
  const [spinning, setSpinning] = useState(false);
  if (!api) return null;
  const { refreshFailed, failedCount } = api;
  const hasFailed = failedCount > 0;

  const handleClick = () => {
    const reloaded = refreshFailed();
    if (reloaded > 0) {
      setSpinning(true);
      window.setTimeout(() => setSpinning(false), 3000);
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={!hasFailed}
      title={
        hasFailed
          ? `Перезагрузить незагруженные изображения (${failedCount})`
          : "Незагруженных изображений нет"
      }
      className="relative flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent"
    >
      <RotateCw className={`h-4 w-4 ${spinning ? "animate-spin" : ""}`} />
      Refresh
      {hasFailed && (
        <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
          {failedCount}
        </span>
      )}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <div
      className={`h-5 w-5 animate-spin rounded-full border-2 border-muted border-t-primary ${className ?? ""}`}
    />
  );
}
