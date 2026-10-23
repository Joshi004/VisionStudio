import { Alert, Badge, Button, Group, Loader, Paper, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useAcceptAsIs,
  useStaleness,
  type AcceptStage,
  type StalenessItem,
} from "../../api/staleness";

type StalenessPanelProps = {
  projectId: number;
};

/**
 * The stages that "Accept as is" is offered for. The server decides which items can be accepted;
 * this only narrows the stage name to the type the request takes.
 */
const ACCEPT_STAGES: readonly string[] = [
  "story_bible",
  "character_discovery",
  "environment_discovery",
  "scene_discovery",
  "relations",
  "scene_definitions",
  "events",
  "scene_staging",
  "speech_units",
  "shot_plans",
  "shot_definitions",
  "references",
  "prompts",
];

function isAcceptStage(stage: string): stage is AcceptStage {
  return ACCEPT_STAGES.includes(stage);
}

function itemKey(item: StalenessItem): string {
  return [item.stage, item.scene_id, item.shot_id, item.discovery_id, item.unit_id].join("/");
}

/**
 * Everything in the project that is out of date, by step, with the reasons. An artifact whose
 * content is still right can be kept as it is ("Accept as is"): that makes no job and calls no
 * model, and what was made from it stays as it is. For the rest, make it again in its own
 * panel.
 */
export function StalenessPanel({ projectId }: StalenessPanelProps) {
  const { data, isLoading, isError, error } = useStaleness(projectId);
  const accept = useAcceptAsIs(projectId);

  function acceptItem(item: StalenessItem) {
    if (!isAcceptStage(item.stage)) {
      return;
    }
    accept.mutate({ stage: item.stage, sceneId: item.scene_id, shotId: item.shot_id });
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>What is out of date</Title>
            <Text size="sm" c="dimmed">
              Something is out of date when what it was made from has changed since. Accept as is
              keeps it and records that it was made from what is current now. It makes nothing
              again, and what was made from it stays as it is. Work from the top: a step that
              needs an earlier one to be current is refused until that one is.
              To make what is out of date again, choose &quot;Only what is out
              of date&quot; in the &quot;Run the whole story&quot; panel and press
              Regenerate out-of-date.
            </Text>
          </Stack>
          {data !== undefined && (
            <Badge color={data.count === 0 ? "green" : "orange"} variant="light">
              {data.count === 0 ? "All up to date" : `${data.count} out of date`}
            </Badge>
          )}
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load what is out of date">
            {describeError(error)}
          </Alert>
        )}
        {accept.isError && (
          <Alert color="red" title="Could not accept it as it is">
            {describeError(accept.error)}
          </Alert>
        )}

        {data?.groups.map((group) => (
          <Stack key={group.step} gap={6}>
            <Group gap="xs">
              <Text fw={600} size="sm">
                {group.label}
              </Text>
              <Badge size="sm" variant="light" color="orange">
                {group.items.length}
              </Badge>
            </Group>
            {group.items.map((item) => (
              <Group key={itemKey(item)} justify="space-between" align="flex-start" wrap="nowrap">
                <Stack gap={2}>
                  <Text size="sm">{item.title}</Text>
                  {item.reasons.map((reason) => (
                    <Text key={reason} size="xs" c="dimmed">
                      {reason}
                    </Text>
                  ))}
                </Stack>
                {item.acceptable && (
                  <Button
                    size="compact-xs"
                    variant="default"
                    onClick={() => acceptItem(item)}
                    loading={accept.isPending}
                    style={{ flexShrink: 0 }}
                  >
                    Accept as is
                  </Button>
                )}
              </Group>
            ))}
          </Stack>
        ))}
      </Stack>
    </Paper>
  );
}
