import { useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Collapse,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { Link } from "react-router";

import {
  useDefineAllEnvironments,
  useDefineOneEnvironment,
  useEnvironmentDefinitions,
  useReplaceEnvironmentPicture,
  useRetryEnvironmentPicture,
  type EnvironmentDefinitionEntry,
} from "../../api/environmentDefinitions";
import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import { EnvironmentDefinitionView } from "../environmentLab/EnvironmentDefinitionView";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ArtifactViewer } from "./ArtifactViewer";
import { PromptHoverCard } from "./PromptHoverCard";

type EnvironmentDefinitionsPanelProps = {
  projectId: number;
};

const STATUS: Record<EnvironmentDefinitionEntry["status"], { label: string; color: string }> = {
  unlinked: { label: "Not linked", color: "gray" },
  not_defined: { label: "Not defined", color: "gray" },
  defined: { label: "Defined", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

function labPath(environmentId: number): string {
  return `/lab/environments?environment=${environmentId}`;
}

type PictureProps = {
  entry: EnvironmentDefinitionEntry;
  busy: boolean;
  onRetry: () => void;
  onReplace: () => void;
};

/**
 * The canonical picture of the version the project pins. It is made by itself once the
 * definition is saved, so this shows how that is going, the picture when it is ready (with
 * Replace picture), and a Retry when it failed or was never started.
 */
function PictureBlock({ entry, busy, onRetry, onReplace }: PictureProps) {
  const picture = entry.picture;
  if (picture.status === "unavailable") {
    return null;
  }
  return (
    <Stack gap={4}>
      <Text size="sm" fw={600}>
        Picture
      </Text>
      {picture.status === "in_progress" && (
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="sm">
            {picture.stage === "writing_prompt"
              ? "Writing the picture prompt..."
              : "Drawing the picture. This takes a few minutes."}
          </Text>
        </Group>
      )}
      {picture.status === "ready" && picture.image !== null && (
        <div style={{ maxWidth: 420 }}>
          <PromptHoverCard imageId={picture.image.id} block>
            <img
              src={picture.image.url}
              alt={`${entry.name}, reference picture`}
              loading="lazy"
              style={{
                width: "100%",
                aspectRatio: "16 / 9",
                objectFit: "cover",
                borderRadius: 4,
                display: "block",
                background: "var(--mantine-color-gray-1)",
              }}
            />
          </PromptHoverCard>
        </div>
      )}
      {picture.status === "ready" && entry.status === "defined" && (
        <Group gap="xs">
          <Button size="compact-xs" variant="default" disabled={busy} onClick={onReplace}>
            Replace picture
          </Button>
        </Group>
      )}
      {picture.status === "failed" && (
        <Alert color="red" p="xs" title="The picture could not be made">
          {picture.error ?? "No reason was given."}
        </Alert>
      )}
      {picture.status === "none" && (
        <Text size="sm" c="dimmed">
          No picture for this version yet.
        </Text>
      )}
      {(picture.status === "failed" || picture.status === "none") && (
        <Group gap="xs">
          <Button
            size="compact-xs"
            variant="default"
            disabled={!picture.can_run || busy}
            onClick={onRetry}
          >
            {picture.status === "failed" ? "Retry the picture" : "Make the picture"}
          </Button>
          {!picture.can_run && picture.blocked_reason !== null && (
            <Text size="xs" c="dimmed">
              {picture.blocked_reason}
            </Text>
          )}
        </Group>
      )}
    </Stack>
  );
}

type EntryRowProps = {
  entry: EnvironmentDefinitionEntry;
  /** True when nothing can be defined yet; the reason is shown once, above the list. */
  projectBlocked: boolean;
  busy: boolean;
  onDefine: () => void;
  onRetryPicture: () => void;
  onReplacePicture: () => void;
};

/**
 * One environment: its status, the library environment it is saved to and the version the
 * project pins, why its definition is out of date, the job's failure when the last run failed,
 * its picture, and the definition itself, read only.
 */
function EntryRow({
  entry,
  projectBlocked,
  busy,
  onDefine,
  onRetryPicture,
  onReplacePicture,
}: EntryRowProps) {
  const [open, setOpen] = useState(false);
  const job = entry.job;
  const active = isJobActive(job);
  const status = STATUS[entry.status];
  const defined = entry.status === "defined" || entry.status === "out_of_date";
  // Why this one environment cannot be defined, when that is about the environment itself.
  const reason = projectBlocked || active ? null : entry.blocked_reason;

  return (
    <Stack gap={6}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge
          variant="outline"
          color="gray"
          miw={120}
          style={{ flexShrink: 0, textTransform: "none" }}
        >
          {entry.id}
        </Badge>
        <Stack gap={4} style={{ flexGrow: 1 }}>
          <Group gap="xs">
            <Text size="sm" fw={500}>
              {entry.name}
            </Text>
            <Badge variant="light" color={status.color}>
              {status.label}
            </Badge>
            {entry.environment_id !== null && entry.environment_name !== null && (
              <Anchor component={Link} to={labPath(entry.environment_id)} size="sm">
                {entry.environment_name}
              </Anchor>
            )}
            {entry.needs_confirmation && (
              <Badge
                variant="light"
                color="teal"
                title="Chosen from the Character Lab: defining it asks first, because it overwrites the profile"
              >
                from the library
              </Badge>
            )}
            {entry.pinned_version !== null && (
              <Badge variant="light" title="The version of the environment this project uses">
                pins v{entry.pinned_version}
              </Badge>
            )}
            {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
          </Group>
          <Text size="sm" c="dimmed">
            {entry.description}
          </Text>
          {reason !== null && (
            <Text size="xs" c="dimmed">
              {reason}
            </Text>
          )}
          {entry.reasons.map((text) => (
            <Text key={text} size="xs" c="yellow.8">
              {text}
            </Text>
          ))}
          {job?.status === "failed" && (
            <Alert color="red" p="xs" title="The last definition failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
          {defined && (
            <PictureBlock
              entry={entry}
              busy={busy}
              onRetry={onRetryPicture}
              onReplace={onReplacePicture}
            />
          )}
        </Stack>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {entry.definition !== null && (
            <Button size="compact-xs" variant="default" onClick={() => setOpen((value) => !value)}>
              {open ? "Hide the definition" : "Show the definition"}
            </Button>
          )}
          <Button
            size="compact-sm"
            variant="default"
            loading={active}
            disabled={!entry.can_run || busy}
            onClick={onDefine}
          >
            {defined ? "Re-define" : "Define"}
          </Button>
        </Group>
      </Group>
      {entry.definition !== null && entry.version !== null && (
        <Collapse expanded={open}>
          <ArtifactViewer
            title="Definition"
            version={entry.version.version}
            source={entry.version.source}
            jobId={entry.version.job_id}
            createdAt={entry.version.created_at}
          >
            <EnvironmentDefinitionView definition={entry.definition} />
          </ArtifactViewer>
        </Collapse>
      )}
    </Stack>
  );
}

/**
 * The Environment Definition stage: one model call per linked environment writes its
 * architecture, layout, look, landmarks, mood and continuity rules. The definition is saved onto
 * the environment's Character Lab profile as a new version, the project pins that version, and
 * its canonical picture is made by itself. **Define all** covers the environments made for this
 * project; one chosen from the library is defined on its own, after the user confirms that its
 * profile will be overwritten.
 */
export function EnvironmentDefinitionsPanel({ projectId }: EnvironmentDefinitionsPanelProps) {
  const { data, isLoading, isError, error } = useEnvironmentDefinitions(projectId);
  const defineAll = useDefineAllEnvironments(projectId);
  const defineOne = useDefineOneEnvironment(projectId);
  const retryPicture = useRetryEnvironmentPicture(projectId);
  const replacePicture = useReplaceEnvironmentPicture(projectId);
  // The environment waiting for the user to agree to overwrite its profile.
  const [confirming, setConfirming] = useState<EnvironmentDefinitionEntry | null>(null);
  // The environment waiting for the user to agree to a new picture.
  const [replacing, setReplacing] = useState<EnvironmentDefinitionEntry | null>(null);

  const busy =
    defineAll.isPending ||
    defineOne.isPending ||
    retryPicture.isPending ||
    replacePicture.isPending;
  const entries = data?.entries ?? [];
  const projectBlocked = (data?.blocked_reason ?? null) !== null;
  // What "Define all" would start: the linked environments made for this project that may run
  // and are not defined and up to date already.
  const allCount = entries.filter(
    (entry) => entry.can_run && !entry.needs_confirmation && entry.status !== "defined",
  ).length;
  const skipped = defineAll.data?.skipped ?? [];

  const define = (entry: EnvironmentDefinitionEntry) => {
    if (entry.needs_confirmation) {
      setConfirming(entry);
    } else {
      defineOne.mutate({ discoveryId: entry.id, confirmOverwrite: false });
    }
  };

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Environment definitions</Title>
            <Text size="sm" c="dimmed">
              Writes each environment&apos;s architecture, layout, look, landmarks and mood, saves
              them to its Character Lab environment as a new version that this project pins, and
              makes its reference picture.
            </Text>
          </Stack>
          <Button
            onClick={() => defineAll.mutate()}
            loading={defineAll.isPending}
            disabled={isLoading || isError || busy || projectBlocked || allCount === 0}
          >
            Define all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the definitions">
            {describeError(error)}
          </Alert>
        )}
        {defineAll.isError && (
          <Alert color="red" title="Could not start the definitions">
            {describeError(defineAll.error)}
          </Alert>
        )}
        {defineOne.isError && (
          <Alert color="red" title="Could not start the definition">
            {describeError(defineOne.error)}
          </Alert>
        )}
        {retryPicture.isError && (
          <Alert color="red" title="Could not start the picture">
            {describeError(retryPicture.error)}
          </Alert>
        )}
        {replacePicture.isError && (
          <Alert color="red" title="Could not replace the picture">
            {describeError(replacePicture.error)}
          </Alert>
        )}
        {skipped.length > 0 && (
          <Alert color="blue" title="Not started">
            <Stack gap={2}>
              {skipped.map((item) => (
                <Text key={item.discovery_id} size="sm">
                  {item.name}: {item.reason}
                </Text>
              ))}
            </Stack>
          </Alert>
        )}
        {data && data.blocked_reason !== null && (
          <Text size="sm" c="dimmed">
            {data.blocked_reason}
          </Text>
        )}
        {data && data.discovery_version === null && (
          <Text size="sm" c="dimmed">
            Find the environments first (above), link them to the Character Lab, find the scenes,
            then define them here.
          </Text>
        )}
        {entries.length > 0 && <Divider />}

        {entries.map((entry) => (
          <EntryRow
            key={entry.id}
            entry={entry}
            projectBlocked={projectBlocked}
            busy={busy}
            onDefine={() => define(entry)}
            onRetryPicture={() => retryPicture.mutate(entry.id)}
            onReplacePicture={() => setReplacing(entry)}
          />
        ))}
      </Stack>

      <Modal
        opened={replacing !== null}
        onClose={() => setReplacing(null)}
        title="Replace the picture?"
        centered
      >
        {replacing && (
          <Stack gap="md">
            <Text size="sm">
              A new reference picture is drawn for {replacing.name}. The project then uses a new
              version of the environment, and the old picture stays with its old version. The
              pictures of its states and the shots that used the old picture will read as out of
              date. Nothing is made again by itself.
            </Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setReplacing(null)}>
                Cancel
              </Button>
              <Button
                onClick={() => {
                  replacePicture.mutate(replacing.id);
                  setReplacing(null);
                }}
              >
                Replace picture
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>

      <Modal
        opened={confirming !== null}
        onClose={() => setConfirming(null)}
        title="Overwrite this environment?"
        centered
      >
        {confirming && (
          <Stack gap="md">
            <Text size="sm">
              {confirming.environment_name ?? confirming.name} was chosen from the Character Lab.
              Defining it replaces its description, atmosphere and era with the new definition, and
              adds a new version. What it has now stays readable in its version history.
            </Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setConfirming(null)}>
                Cancel
              </Button>
              <Button
                color="red"
                onClick={() => {
                  defineOne.mutate({ discoveryId: confirming.id, confirmOverwrite: true });
                  setConfirming(null);
                }}
              >
                Define and overwrite
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Paper>
  );
}
