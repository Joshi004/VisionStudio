import { createContext, useCallback, useContext, useEffect, useState } from "react";

/** Which stage panels of a project page are open, and how to open or close one. */
export type ProjectPanels = {
  isOpen: (key: string) => boolean;
  setOpen: (key: string, open: boolean) => void;
  openPanel: (key: string) => void;
};

/** Outside a project page nothing is collapsed, so the default never hides a panel. */
export const ProjectPanelsContext = createContext<ProjectPanels>({
  isOpen: () => true,
  setOpen: () => undefined,
  openPanel: () => undefined,
});

export function useProjectPanels(): ProjectPanels {
  return useContext(ProjectPanelsContext);
}

function storageKey(projectId: number): string {
  return `visiostudio.project.${projectId}.openPanels`;
}

/** What the browser remembers. Anything unexpected (bad JSON, no storage) means nothing is open. */
function readOpenKeys(projectId: number): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(storageKey(projectId)) ?? "[]");
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}

function writeOpenKeys(projectId: number, keys: string[]) {
  try {
    localStorage.setItem(storageKey(projectId), JSON.stringify(keys));
  } catch {
    // Private mode or a full quota: the panels still work, they are just not remembered.
  }
}

/**
 * The open panels of one project, remembered in the browser per project. A panel that is not
 * open is not rendered, so it makes no request and does not poll.
 */
export function useOpenPanels(projectId: number): ProjectPanels {
  const [state, setState] = useState(() => ({ projectId, keys: readOpenKeys(projectId) }));

  // Another project in the same page instance: load what that project had open.
  let keys = state.keys;
  if (state.projectId !== projectId) {
    keys = readOpenKeys(projectId);
    setState({ projectId, keys });
  }

  useEffect(() => {
    if (Number.isInteger(projectId) && projectId > 0) {
      writeOpenKeys(projectId, keys);
    }
  }, [projectId, keys]);

  const setOpen = useCallback(
    (key: string, open: boolean) => {
      setState((current) => {
        const without = current.keys.filter((item) => item !== key);
        return { ...current, keys: open ? [...without, key] : without };
      });
    },
    [],
  );

  const openPanel = useCallback((key: string) => setOpen(key, true), [setOpen]);
  const isOpen = useCallback((key: string) => keys.includes(key), [keys]);

  return { isOpen, setOpen, openPanel };
}
