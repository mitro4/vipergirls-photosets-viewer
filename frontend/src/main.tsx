import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import DownloadsPage from "./pages/DownloadsPage";
import LikedPage from "./pages/LikedPage";
import ThreadPage from "./pages/ThreadPage";
import SearchPage from "./pages/SearchPage";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 60_000, refetchOnWindowFocus: false },
  },
});

// CategoryPage is rendered directly by <App> (DOM-level keep-alive, see
// App.tsx) — these routes only exist so the router accepts "/" and
// "/forum/:forumId" as valid paths instead of 404-ing. The Outlet renders an
// empty fragment for them; App renders CategoryPage alongside it. Only
// thread/search flow through the Outlet as real page content.
const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <></> },
      { path: "forum/:forumId", element: <></> },
      { path: "thread/:threadId", element: <ThreadPage /> },
      { path: "liked", element: <LikedPage /> },
      { path: "downloads", element: <DownloadsPage /> },
      { path: "search", element: <SearchPage /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>
);
