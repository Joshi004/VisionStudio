import type { ReactNode } from "react";
import { Button, Group, Paper, Stack, Text } from "@mantine/core";

import { useProjectPanels } from "./projectPanels";

type CollapsiblePanelProps = {
  /** Names the panel in the remembered open list (the step key for a pipeline step). */
  panelKey: string;
  title: string;
  /** The element id other code scrolls to; it exists whether the panel is open or not. */
  anchorId?: string;
  children: ReactNode;
};

/**
 * A stage panel that is rendered only while it is open. Closed, it is one line, and the panel
 * inside makes no request and does not poll.
 */
export function CollapsiblePanel({ panelKey, title, anchorId, children }: CollapsiblePanelProps) {
  const { isOpen, setOpen } = useProjectPanels();
  const open = isOpen(panelKey);

  if (!open) {
    return (
      <Paper id={anchorId} withBorder p="xs" px="md" radius="md">
        <Group justify="space-between">
          <Text fw={500}>{title}</Text>
          <Button variant="default" size="compact-sm" onClick={() => setOpen(panelKey, true)}>
            Open
          </Button>
        </Group>
      </Paper>
    );
  }

  return (
    <Stack id={anchorId} gap={4}>
      <Group justify="flex-end">
        <Button variant="subtle" size="compact-xs" onClick={() => setOpen(panelKey, false)}>
          Close {title}
        </Button>
      </Group>
      {children}
    </Stack>
  );
}
