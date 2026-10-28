import { Suspense, useMemo } from "react";
import { Badge, Group, Loader, Paper, Stack, Text, Title } from "@mantine/core";
import { useNavigate } from "react-router";

import type { BoardStep } from "../../api/pipelineBoard";
import type { ProjectDetail } from "../../api/projects";
import { ProjectPanelsContext, type ProjectPanels } from "../story/projectPanels";
import { STATUS_DISPLAY, WORKSPACE_ITEMS, stepPath } from "./boardSteps";
import { StepPanel } from "./StepPanel";

type BoardStepDetailProps = {
  project: ProjectDetail;
  /** The open step or workspace key. None shows a hint and loads nothing. */
  stepKey: string | null;
  /** The board's row for that step, when the board has loaded and the key is a step. */
  step: BoardStep | undefined;
};

/**
 * The right-hand side of the board: the existing stage panel of the open step, loaded only
 * now. Its own requests start when it is shown and stop when another step is opened.
 */
export function BoardStepDetail({ project, stepKey, step }: BoardStepDetailProps) {
  const navigate = useNavigate();

  // Panels that ask to show another step (the review point does) move the selection here.
  const panels = useMemo<ProjectPanels>(
    () => ({
      isOpen: () => true,
      setOpen: () => undefined,
      openPanel: (key) => void navigate(stepPath(project.id, key)),
    }),
    [navigate, project.id],
  );

  if (stepKey === null) {
    return (
      <Paper withBorder p="xl" radius="md">
        <Text c="dimmed">Choose a step on the left to open it.</Text>
      </Paper>
    );
  }

  const title =
    step?.label ?? WORKSPACE_ITEMS.find((item) => item.key === stepKey)?.label ?? stepKey;
  const status = step !== undefined ? STATUS_DISPLAY[step.status] : null;

  return (
    <ProjectPanelsContext.Provider value={panels}>
      <Stack gap="sm">
        <Group gap="sm">
          <Title order={3}>{title}</Title>
          {status !== null && (
            <Badge variant="light" color={status.color}>
              {status.label}
            </Badge>
          )}
        </Group>
        <Suspense key={stepKey} fallback={<Loader size="sm" />}>
          <StepPanel stepKey={stepKey} project={project} />
        </Suspense>
      </Stack>
    </ProjectPanelsContext.Provider>
  );
}
