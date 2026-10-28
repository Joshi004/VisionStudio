import { createBrowserRouter, Navigate } from "react-router";

import { AppLayout } from "./components/AppLayout";
import { RouteError } from "./components/RouteError";
import { ActivityPage } from "./pages/ActivityPage";
import { LabPage } from "./pages/LabPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PipelineBoardPage } from "./pages/PipelineBoardPage";
import { ProjectSettingsPage } from "./pages/ProjectSettingsPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SettingsPage } from "./pages/SettingsPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="/projects" replace /> },
      { path: "projects", element: <ProjectsPage /> },
      // The board is the project's page. The step that is open is in the address.
      { path: "projects/:projectId", element: <PipelineBoardPage /> },
      { path: "projects/:projectId/pipeline/:stepKey", element: <PipelineBoardPage /> },
      // The long page with every panel. It is loaded only when it is opened, so its panels do
      // not weigh on the first load.
      {
        path: "projects/:projectId/classic",
        lazy: async () => ({ Component: (await import("./pages/ProjectPage")).ProjectPage }),
      },
      { path: "projects/:projectId/settings", element: <ProjectSettingsPage /> },
      { path: "activity", element: <ActivityPage /> },
      // One Lab with a tab for each of the labs. The tab is in the address.
      { path: "lab", element: <Navigate to="/lab/characters" replace /> },
      { path: "lab/:tab", element: <LabPage /> },
      // The Talking character tab was replaced by the Characters tab.
      { path: "lab/talk", element: <Navigate to="/lab/characters" replace /> },
      // The addresses the three labs had before they became tabs.
      { path: "image-lab", element: <Navigate to="/lab/image" replace /> },
      { path: "video-lab", element: <Navigate to="/lab/video" replace /> },
      { path: "voice-lab", element: <Navigate to="/lab/voice" replace /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
