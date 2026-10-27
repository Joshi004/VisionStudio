import { Alert, Group, Loader, Paper, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useProjectCast } from "../../api/projectCast";

type ExplainerCastPanelProps = {
  projectId: number;
};

/**
 * The cast of an explainer: its presenter and its set, chosen when the project was created.
 * They cannot be changed, and the presenter's voice is also the narrator's.
 */
export function ExplainerCastPanel({ projectId }: ExplainerCastPanelProps) {
  const cast = useProjectCast(projectId);

  if (cast.isPending) {
    return <Loader size="sm" />;
  }
  if (cast.isError) {
    return <Alert color="red">{describeError(cast.error)}</Alert>;
  }
  const presenter = cast.data.characters[0];
  const set = cast.data.environments[0];

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="xs">
        <Title order={4}>Presenter and set</Title>
        <Group gap="xs">
          <Text fw={500}>Presenter:</Text>
          <Text>{presenter?.name ?? "None"}</Text>
        </Group>
        <Text size="xs" c="dimmed">
          The presenter speaks on camera, and its voice is also the narrator&apos;s, so the
          voice-over and the presenter sound alike.
        </Text>
        <Group gap="xs">
          <Text fw={500}>Set:</Text>
          <Text>{set?.name ?? "A studio designed from the script"}</Text>
        </Group>
        <Text size="xs" c="dimmed">
          The presenter and the set were chosen when the project was created and cannot be
          changed.
        </Text>
      </Stack>
    </Paper>
  );
}
