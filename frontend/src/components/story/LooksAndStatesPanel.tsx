import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import {
  useLookStateResolution,
  useResolveLooksAndStates,
  type LookStateItem,
  type LookStateScene,
} from "../../api/lookStateResolution";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { PromptHoverCard } from "./PromptHoverCard";

type LooksAndStatesPanelProps = {
  projectId: number;
};

const HOW: Record<
  LookStateItem["how"],
  { label: string; color: string; title: string }
> = {
  default: {
    label: "Default",
    color: "gray",
    title: "The canonical look or reference, as defined",
  },
  reuse: {
    label: "Reused",
    color: "blue",
    title: "A named look or state that already existed in the library",
  },
  new: {
    label: "New",
    color: "green",
    title: "Created by this resolution; its pictures are made later",
  },
};

type ItemRowProps = {
  /** What kind of thing is asked for, shown before the subject's name. */
  kind: "Place" | "Look";
  item: LookStateItem;
};

/** One request of a scene, in the scene's own words, and what it resolved to. */
function ItemRow({ kind, item }: ItemRowProps) {
  const how = HOW[item.how];
  return (
    <Group gap="xs" align="flex-start" wrap="nowrap">
      <Text size="xs" c="dimmed" w={90} style={{ flexShrink: 0 }}>
        {kind}: {item.subject_name}
      </Text>
      <Stack gap={0} style={{ flexGrow: 1 }}>
        <Group gap="xs">
          <Text size="sm">&ldquo;{item.request}&rdquo;</Text>
          <Text size="sm" c="dimmed">
            &rarr;
          </Text>
          {item.id !== null ? (
            <Text size="sm" fw={500}>
              {item.name ?? item.id}
            </Text>
          ) : (
            <Text size="sm" fw={500}>
              As defined
            </Text>
          )}
          <Badge variant="light" color={how.color} title={how.title}>
            {how.label}
          </Badge>
        </Group>
        {item.description !== null && (
          <Text size="xs" c="dimmed">
            {item.description}
          </Text>
        )}
      </Stack>
    </Group>
  );
}

function SceneRow({ scene }: { scene: LookStateScene }) {
  return (
    <Stack gap={4}>
      <Group gap="xs">
        <Badge
          variant="outline"
          color="gray"
          miw={40}
          style={{ textTransform: "none" }}
        >
          {scene.index}
        </Badge>
        <Text size="sm" fw={500}>
          {scene.title}
        </Text>
        {!scene.resolved && (
          <Badge variant="light" color="gray">
            Not resolved
          </Badge>
        )}
        {scene.resolved && !scene.current && (
          <Badge
            variant="light"
            color="yellow"
            title="The scene was defined again after this was resolved"
          >
            Out of date
          </Badge>
        )}
      </Group>
      {scene.environment !== null && (
        <ItemRow kind="Place" item={scene.environment} />
      )}
      {scene.looks.map((look) => (
        <ItemRow key={look.subject_id} kind="Look" item={look} />
      ))}
    </Stack>
  );
}

/**
 * The look and environment-state resolution: after all scenes are defined, one model call maps
 * every look and state they asked for to the default, an existing named look or state, or one
 * new entry that scenes with the same need share. Pictures for the new ones are made later.
 */
export function LooksAndStatesPanel({ projectId }: LooksAndStatesPanelProps) {
  const { data, isLoading, isError, error } = useLookStateResolution(projectId);
  const resolve = useResolveLooksAndStates(projectId);

  const job = data?.job ?? null;
  const active = isJobActive(job);
  const version = data?.version ?? null;
  const scenes = data?.scenes ?? [];
  const reasons = data?.reasons ?? [];

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Looks and environment states</Title>
            <Text size="sm" c="dimmed">
              Settles the outfits and conditions (such as night) that the scenes
              asked for in their own words, so that the same one is drawn only
              once. It needs every scene to be defined.
            </Text>
          </Stack>
          <Group gap="xs">
            {version !== null && (
              <PromptHoverCard jobId={version.job_id} source={version.source}>
                <Badge variant="light" style={{ cursor: "help" }}>
                  v{version.version}
                </Badge>
              </PromptHoverCard>
            )}
            <Button
              onClick={() => resolve.mutate()}
              loading={resolve.isPending || active}
              disabled={isLoading || isError || !(data?.can_run ?? false)}
            >
              {version !== null ? "Resolve again" : "Resolve looks and states"}
            </Button>
          </Group>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the looks and states">
            {describeError(error)}
          </Alert>
        )}
        {resolve.isError && (
          <Alert color="red" title="Could not start the resolution">
            {describeError(resolve.error)}
          </Alert>
        )}
        {job !== null && job.status !== "succeeded" && (
          <Group gap="xs">
            <JobStatusBadge job={job} />
          </Group>
        )}
        {job?.status === "failed" && (
          <Alert color="red" p="xs" title="The last resolution failed">
            {job.error ?? "The job failed."}
          </Alert>
        )}
        {data && data.blocked_reason !== null && !active && (
          <Text size="sm" c="dimmed">
            {data.blocked_reason}
          </Text>
        )}
        {reasons.map((text) => (
          <Text key={text} size="xs" c="yellow.8">
            {text}
          </Text>
        ))}
        {scenes.length > 0 && version !== null && <Divider />}

        {version !== null &&
          scenes.map((scene) => <SceneRow key={scene.id} scene={scene} />)}
      </Stack>
    </Paper>
  );
}
