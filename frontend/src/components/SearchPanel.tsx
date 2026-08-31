import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Search as SearchIcon, X } from "lucide-react";
import { api } from "../api/client";

type Mode = "threads" | "posts";

interface SearchPanelProps {
  onClose: () => void;
}

export function SearchPanel({ onClose }: SearchPanelProps) {
  const navigate = useNavigate();
  const { data: groups } = useQuery({
    queryKey: ["categories"],
    queryFn: api.categories,
    staleTime: 5 * 60_000,
  });

  const topCategories = (groups ?? []).flatMap((g) => g.categories);

  const [q, setQ] = useState("");
  const [mode, setMode] = useState<Mode>("threads");
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const toggleCat = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const runSearch = () => {
    if (q.trim().length < 2) return;
    const forums = [...selected].sort((a, b) => a - b).join(",");
    const params = new URLSearchParams({ q: q.trim(), mode, page: "1" });
    if (forums) params.set("forums", forums);
    onClose();
    navigate(`/search?${params.toString()}`);
  };

  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Enter") runSearch();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, q, mode, selected]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-[12vh] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl overflow-hidden rounded-2xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 border-b border-border p-4">
          <div className="relative flex-1">
            <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search the forum…"
              className="w-full rounded-lg border border-border bg-background py-2.5 pl-9 pr-3 text-sm outline-none focus:border-primary"
            />
          </div>
          <button
            onClick={runSearch}
            disabled={q.trim().length < 2}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-40"
          >
            Search
          </button>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-muted-foreground hover:bg-secondary"
            title="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Mode + sections */}
        <div className="flex flex-col gap-3 p-4">
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground">Mode:</span>
            <div className="flex overflow-hidden rounded-lg border border-border text-xs">
              <button
                onClick={() => setMode("threads")}
                className={`px-3 py-1.5 font-medium transition-colors ${
                  mode === "threads"
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-secondary"
                }`}
              >
                Threads
              </button>
              <button
                onClick={() => setMode("posts")}
                className={`px-3 py-1.5 font-medium transition-colors ${
                  mode === "posts"
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-secondary"
                }`}
              >
                Posts
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">Sections:</span>
            {topCategories.map((cat) => (
              <button
                key={cat.forum_id}
                onClick={() => toggleCat(cat.forum_id)}
                className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                  selected.has(cat.forum_id)
                    ? "border-primary bg-primary/15 text-primary"
                    : "border-border text-muted-foreground hover:bg-secondary"
                }`}
              >
                {cat.title}
              </button>
            ))}
            {selected.size > 0 && (
              <button
                onClick={() => setSelected(new Set())}
                className="text-xs text-muted-foreground underline hover:text-foreground"
              >
                Clear ({selected.size})
              </button>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground/70">
            No section selected — searches all sections. Press Enter to search.
          </p>
        </div>
      </div>
    </div>
  );
}
