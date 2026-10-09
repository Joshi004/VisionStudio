import { createBrowserRouter, Navigate } from "react-router";

import { AppLayout } from "./components/AppLayout";
import { RouteError } from "./components/RouteError";
import { ActivityPage } from "./pages/ActivityPage";
import { ImageLabPage } from "./pages/ImageLabPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ProjectSettingsPage } from "./pages/ProjectSettingsPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { VideoLabPage } from "./pages/VideoLabPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="/projects" replace /> },
      { path: "projects", element: <ProjectsPage /> },
      { path: "projects/:projectId", element: <ProjectPage /> },
      { path: "projects/:projectId/settings", element: <ProjectSettingsPage /> },
      { path: "activity", element: <ActivityPage /> },
      { path: "image-lab", element: <ImageLabPage /> },
      { path: "video-lab", element: <VideoLabPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
