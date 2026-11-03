import { Alert, Anchor, Badge, Code, Collapse, Group, Loader, Stack, Text } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";

import type { GraphicRender } from "../../api/graphicsLab";
import { isJobActive } from "../../api/polling";
import { BLOCK_LABELS, readBlockInput } from "./graphicsLabView";

type GraphicsBlockSceneProps = {
  /** The newest render of the building-blocks engine. */
  render: GraphicRender;
};

/**
 * What the building-blocks engine draws from: the scene the model designed (which blocks it
 * used), and what the layout check found. While the scene is being written it says so.
 */
export function GraphicsBlockScene({ render }: GraphicsBlockSceneProps) {
  const scene = readBlockInput(render.input);
  const [showScene, { toggle }] = useDisclosure(false);

  if (isJobActive(render.input_job)) {
    return (
      <Group gap="xs">
        <Loader size="xs" />
        <Text size="xs" c="dimmed">
          Designing the scene{render.input_job?.phase ? `: ${render.input_job.phase}` : ""}
        </Text>
      </Group>
    );
  }
  if (scene === null) {
    return null;
  }

  return (
    <Stack gap={6}>
      <Group gap={4}>
        {scene.blocks.map((block, index) => (
          <Badge key={`${block}-${index}`} variant="light" size="sm">
            {BLOCK_LABELS[block] ?? block}
          </Badge>
        ))}
      </Group>
      {!scene.checked ? (
        <Text size="xs" c="dimmed" style={{ wordBreak: "break-word" }}>
          The layout was not checked{scene.reason ? `: ${scene.reason}` : "."}
        </Text>
      ) : scene.problems.length > 0 ? (
        <Alert color="yellow" p="xs" title="Layout problems">
          <Stack gap={2}>
            {scene.problems.map((problem) => (
              <Text key={problem} size="xs" style={{ wordBreak: "break-word" }}>
                {problem}
              </Text>
            ))}
          </Stack>
        </Alert>
      ) : (
        <Text size="xs" c="dimmed">
          Layout checked: no problems{scene.askedAgain ? " (after asking the model again)" : ""}.
        </Text>
      )}
      <Anchor component="button" type="button" size="xs" onClick={toggle} ta="left">
        {showScene ? "Hide the scene" : "Show the scene"}
      </Anchor>
      <Collapse expanded={showScene}>
        <Code block style={{ maxHeight: 280, overflow: "auto" }}>
          {JSON.stringify(render.input, null, 2)}
        </Code>
      </Collapse>
    </Stack>
  );
}
