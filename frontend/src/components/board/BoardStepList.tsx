import { Badge, Group, NavLink, Stack, Text, Tooltip } from "@mantine/core";
import { Link } from "react-router";

import type { BoardStep, PipelineBoard } from "../../api/pipelineBoard";
import {
  GROUP_LABELS,
  GROUP_ORDER,
  STATUS_DISPLAY,
  WORKSPACE_ITEMS,
  stepPath,
} from "./boardSteps";

type BoardStepListProps = {
  projectId: number;
  board: PipelineBoard;
  /** The step or workspace item that is open, if any. */
  selectedKey: string | null;
};

/** The numbers worth showing under a step's name: progress, work going on, what is wrong. */
function detailParts(step: BoardStep, labelOf: (key: string) => string): string[] {
  if (step.status === "off") {
    return ["Switched off for this project"];
  }
  const parts: string[] = [];
  if (step.total > 1) {
    parts.push(`${step.done} of ${step.total}`);
  }
  if (step.active > 0) {
    parts.push(`${step.active} running`);
  }
  if (step.stale > 0) {
    parts.push(`${step.stale} out of date`);
  }
  if (step.failed > 0) {
    parts.push(`${step.failed} failed`);
  }
  if (step.status === "waiting" && step.blocked_by.length > 0) {
    parts.push(`waiting for: ${step.blocked_by.map(labelOf).join(", ")}`);
  }
  return parts;
}

/** The steps grouped, groups in `GROUP_ORDER`, steps in the order the backend gave them. */
function groupSteps(steps: BoardStep[]): { group: string; steps: BoardStep[] }[] {
  const byGroup = new Map<string, BoardStep[]>();
  for (const step of steps) {
    byGroup.set(step.group, [...(byGroup.get(step.group) ?? []), step]);
  }
  const known = GROUP_ORDER.filter((group) => byGroup.has(group));
  const unknown = [...byGroup.keys()].filter((group) => !GROUP_ORDER.includes(group));
  return [...known, ...unknown].map((group) => ({ group, steps: byGroup.get(group) ?? [] }));
}

/**
 * Every step of the pipeline in one compact list. A row is a link, so the open step is in the
 * address and the list works with the keyboard.
 */
export function BoardStepList({ projectId, board, selectedKey }: BoardStepListProps) {
  const labelOf = (key: string) => board.steps.find((step) => step.key === key)?.label ?? key;
  const nextKey = board.next_keys[0];

  return (
    <Stack gap="md">
      <Stack gap={2}>
        <Text size="xs" fw={700} c="dimmed" tt="uppercase">
          Project
        </Text>
        {WORKSPACE_ITEMS.map((item) => (
          <NavLink
            key={item.key}
            component={Link}
            to={stepPath(projectId, item.key)}
            label={item.label}
            active={selectedKey === item.key}
          />
        ))}
      </Stack>

      {groupSteps(board.steps).map(({ group, steps }) => (
        <Stack key={group} gap={2}>
          <Text size="xs" fw={700} c="dimmed" tt="uppercase">
            {GROUP_LABELS[group] ?? group}
          </Text>
          {steps.map((step) => {
            const status = STATUS_DISPLAY[step.status];
            const parts = detailParts(step, labelOf);
            const reason = step.status === "attention" ? step.blocked_reason : null;
            return (
              <Tooltip
                key={step.key}
                label={reason}
                disabled={reason === null}
                multiline
                w={320}
                position="right"
                withArrow
              >
                <NavLink
                  component={Link}
                  to={stepPath(projectId, step.key)}
                  active={selectedKey === step.key}
                  label={
                    <Text size="sm" c={step.status === "off" ? "dimmed" : undefined}>
                      {step.label}
                    </Text>
                  }
                  description={
                    parts.length > 0 || reason !== null ? (
                      <Stack gap={0}>
                        {parts.length > 0 && (
                          <Text size="xs" c="dimmed">
                            {parts.join(", ")}
                          </Text>
                        )}
                        {reason !== null && (
                          <Text size="xs" c="red.8" lineClamp={1}>
                            {reason}
                          </Text>
                        )}
                      </Stack>
                    ) : undefined
                  }
                  rightSection={
                    <Group gap={4} wrap="nowrap">
                      {step.key === nextKey && (
                        <Badge size="xs" variant="filled" color="violet">
                          Next
                        </Badge>
                      )}
                      <Badge size="sm" variant="light" color={status.color}>
                        {status.label}
                      </Badge>
                    </Group>
                  }
                />
              </Tooltip>
            );
          })}
        </Stack>
      ))}
    </Stack>
  );
}
