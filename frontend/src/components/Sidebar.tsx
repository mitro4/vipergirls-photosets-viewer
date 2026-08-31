import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import {
  Archive,
  ExternalLink,
  FolderTree,
  Images,
  LogIn,
  LogOut,
  Settings,
  User,
} from "lucide-react";
import type { CategoryGroupOut } from "../api/client";
import { api } from "../api/client";
import { cn } from "../lib/utils";
import { Spinner } from "../App";

interface SidebarProps {
  groups: CategoryGroupOut[];
  onLoginClick: () => void;
  onSettingsClick: () => void;
  collapsed: boolean;
}

export function Sidebar({ groups, onLoginClick, onSettingsClick, collapsed }: SidebarProps) {
  const queryClient = useQueryClient();

  const { data: auth } = useQuery({
    queryKey: ["auth"],
    queryFn: api.authStatus,
    staleTime: 30_000,
  });

  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: api.config,
    staleTime: 5 * 60_000,
  });

  const logoutMutation = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["auth"] });
    },
  });

  const forumLabel = (config?.forum_url ?? "").replace(/^https?:\/\//, "");

  return (
    <aside
      className={`relative h-full shrink-0 overflow-hidden border-r border-border bg-card/40 transition-[width] duration-200 ease-in-out ${
        collapsed ? "w-0" : "w-64"
      }`}
    >
      <div className="flex h-full w-64 flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Images className="h-4 w-4" />
        </div>
        <div className="flex min-w-0 flex-col">
          <span className="font-semibold leading-tight tracking-tight">Viper Viewer</span>
          {forumLabel && (
            <a
              href={config!.forum_url}
              target="_blank"
              rel="noreferrer"
              title="Open forum"
              className="flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-primary"
            >
              <span className="truncate">{forumLabel}</span>
              <ExternalLink className="h-2.5 w-2.5 shrink-0" />
            </a>
          )}
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto p-2">
        <div className="px-2 py-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Sections
        </div>
        {groups.length === 0 && (
          <div className="flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground">
            <Spinner className="h-4 w-4" /> Loading…
          </div>
        )}
        {groups.map((group) => (
          <div key={group.name} className="mb-1.5">
            <div className="flex items-center gap-1.5 px-2 py-1.5 text-xs font-medium text-muted-foreground">
              <FolderTree className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{group.name}</span>
            </div>
            {group.categories.map((cat) => (
              <div key={cat.forum_id}>
                <NavLink
                  to={`/forum/${cat.forum_id}`}
                  className={({ isActive }) =>
                    cn(
                      "block truncate rounded-md px-3 py-1.5 pl-7 text-sm transition-colors hover:bg-secondary",
                      isActive && "bg-primary/15 font-medium text-primary",
                    )
                  }
                >
                  {cat.title}
                </NavLink>
                {cat.children.map((child) => (
                  <NavLink
                    key={child.forum_id}
                    to={`/forum/${child.forum_id}`}
                    title={child.title}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-1.5 truncate rounded-md px-3 py-1 pl-11 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground",
                        isActive && "bg-primary/15 font-medium text-primary",
                      )
                    }
                  >
                    <Archive className="h-3 w-3 shrink-0 opacity-70" />
                    Archive
                  </NavLink>
                ))}
              </div>
            ))}
          </div>
        ))}
      </nav>

      {/* Auth footer */}
      <div className="space-y-2 border-t border-border p-3">
        <button
          onClick={onSettingsClick}
          className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium transition-colors hover:bg-secondary"
        >
          <Settings className="h-4 w-4" />
          Settings
        </button>
        {auth?.logged_in ? (
          <div className="flex items-center justify-between gap-2 rounded-lg bg-secondary/50 px-3 py-2">
            <div className="flex min-w-0 items-center gap-2">
              <User className="h-4 w-4 shrink-0 text-primary" />
              <span className="truncate text-sm font-medium">{auth.username}</span>
            </div>
            <button
              onClick={() => logoutMutation.mutate()}
              disabled={logoutMutation.isPending}
              title="Log out"
              className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <button
            onClick={onLoginClick}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium transition-colors hover:bg-secondary"
          >
            <LogIn className="h-4 w-4" />
            Login
          </button>
        )}
      </div>
      </div>
    </aside>
  );
}
