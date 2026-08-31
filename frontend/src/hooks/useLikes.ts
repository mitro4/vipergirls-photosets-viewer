import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, LikedOut } from "../api/client";

/**
 * Likes state shared across pages. Reuses the Sidebar/LoginModal `["auth"]`
 * query so login state is consistent app-wide. The liked set is derived from
 * `GET /api/liked` (only fetched when logged in); toggles are optimistic.
 */
export function useLikes() {
  const qc = useQueryClient();
  const { data: auth } = useQuery({
    queryKey: ["auth"],
    queryFn: api.authStatus,
  });
  const loggedIn = !!auth?.logged_in;

  const { data: likedData } = useQuery({
    queryKey: ["liked"],
    queryFn: api.liked,
    enabled: loggedIn,
  });

  const likedIds = new Set((likedData?.items ?? []).map((i) => i.thread_id));

  const toggleMut = useMutation({
    mutationFn: (args: { id: number; like: boolean }) =>
      args.like ? api.likeThread(args.id) : api.unlikeThread(args.id),
    onMutate: async ({ id, like }) => {
      await qc.cancelQueries({ queryKey: ["liked"] });
      const prev = qc.getQueryData<LikedOut>(["liked"]);
      if (prev) {
        const items = like
          ? [
              ...prev.items,
              { thread_id: id, title: "", liked_at: new Date().toISOString() },
            ]
          : prev.items.filter((i) => i.thread_id !== id);
        qc.setQueryData<LikedOut>(["liked"], { items });
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["liked"], ctx.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["liked"] });
    },
  });

  const toggleLike = (id: number) => {
    const like = !likedIds.has(id);
    toggleMut.mutate({ id, like });
  };

  return { loggedIn, likedIds, toggleLike };
}
