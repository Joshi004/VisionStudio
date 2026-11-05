import { Badge, Button, Group, Stack, Text } from "@mantine/core";

import type { GraphicRender } from "../../api/graphicsLab";
import { renderState } from "./graphicsLabView";

type GraphicsAttemptListProps = {
  /** Every render of the engine, newest first. */
  renders: GraphicRender[];
  /** The render the card shows. */
  shownId: number;
  onShow: (renderId: number) => void;
};

const VERDICT_COLORS = { good: "green", usable: "yellow", bad: "red" } as const;

/**
 * The attempts of one engine, newest first. Ask again and Render again add one and never replace
 * one. **Show** puts an attempt in the card: its video joins the synced player, and the verdict
 * and the note under the video are that attempt's.
 */
export function GraphicsAttemptList({ renders, shownId, onShow }: GraphicsAttemptListProps) {
  if (renders.length < 2) {
    return null;
  }
  const attemptOf = new Map(renders.map((render) => [render.id, render.attempt]));

  return (
    <Stack gap={4}>
      <Text size="xs" fw={600} c="dimmed">
        Attempts
      </Text>
      {renders.map((render) => {
        const state = renderState(render);
        const repeated = render.repeat_of !== null ? attemptOf.get(render.repeat_of) : undefined;
        return (
          <Group key={render.id} gap={6} wrap="nowrap" data-attempt={render.attempt}>
            <Text size="xs" fw={500} w={64}>
              Attempt {render.attempt}
            </Text>
            <Badge size="xs" variant="light" color={state.color}>
              {state.busy ? "Working" : state.label}
            </Badge>
            {render.repeat_of !== null && (
              <Text size="xs" c="dimmed">
                {repeated !== undefined ? `repeat of ${repeated}` : "a repeat"}
              </Text>
            )}
            {render.verdict !== null && (
              <Badge size="xs" variant="filled" color={VERDICT_COLORS[render.verdict]}>
                {render.verdict}
              </Badge>
            )}
            <div style={{ marginLeft: "auto" }}>
              {render.id === shownId ? (
                <Text size="xs" c="dimmed">
                  Shown
                </Text>
              ) : (
                <Button size="compact-xs" variant="subtle" onClick={() => onShow(render.id)}>
                  Show
                </Button>
              )}
            </div>
          </Group>
        );
      })}
    </Stack>
  );
}
