interface PaginationProps {
  page: number;
  totalPages: number;
  onChange: (p: number) => void;
  className?: string;
}

// Build the page-number list: always include 1 and `total`, with a 5-page
// window (current ± 2) in between, inserting ellipses where there's a gap.
function pageItems(page: number, total: number): (number | "ellipsis")[] {
  const radius = 2;
  const items: (number | "ellipsis")[] = [];
  const start = Math.max(1, page - radius);
  const end = Math.min(total, page + radius);
  if (start > 1) {
    items.push(1);
    if (start > 2) items.push("ellipsis");
  }
  for (let p = start; p <= end; p++) items.push(p);
  if (end < total) {
    if (end < total - 1) items.push("ellipsis");
    items.push(total);
  }
  return items;
}

export default function Pagination({
  page,
  totalPages,
  onChange,
  className = "",
}: PaginationProps) {
  if (totalPages <= 1) return null;
  const items = pageItems(page, totalPages);
  const edgeBtn =
    "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm border-border hover:bg-accent/20 disabled:opacity-40 disabled:hover:bg-transparent";
  const numBtn = (active: boolean) =>
    `min-w-[2rem] rounded-lg border px-2 py-1.5 text-sm ${
      active
        ? "border-primary bg-primary text-primary-foreground"
        : "border-border hover:bg-accent/20"
    }`;
  return (
    <nav
      className={`flex flex-wrap items-center justify-center gap-1 ${className}`}
      aria-label="Pagination"
    >
      <button
        className={edgeBtn}
        disabled={page <= 1}
        onClick={() => onChange(1)}
        aria-label="First page"
      >
        «
      </button>
      <button
        className={edgeBtn}
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
        aria-label="Previous page"
      >
        ‹
      </button>
      {items.map((it, i) =>
        it === "ellipsis" ? (
          <span key={`e${i}`} className="px-1 text-muted-foreground">
            …
          </span>
        ) : (
          <button
            key={it}
            className={numBtn(it === page)}
            onClick={() => onChange(it)}
            aria-current={it === page ? "page" : undefined}
          >
            {it}
          </button>
        )
      )}
      <button
        className={edgeBtn}
        disabled={page >= totalPages}
        onClick={() => onChange(page + 1)}
        aria-label="Next page"
      >
        ›
      </button>
      <button
        className={edgeBtn}
        disabled={page >= totalPages}
        onClick={() => onChange(totalPages)}
        aria-label="Last page"
      >
        »
      </button>
    </nav>
  );
}
