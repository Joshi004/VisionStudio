import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Code,
  Collapse,
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
  useCompileAllPrompts,
  useCompileOnePrompt,
  useCompileScenePrompts,
  useSaveShotPrompt,
  useShotPrompts,
  type SceneShotPrompts,
  type ShotPromptEntry,
} from "../../api/shotPrompts";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { FeedbackBadge } from "./FeedbackBadge";
import { FeedbackModal } from "./FeedbackModal";
import { PromptHoverCard } from "./PromptHoverCard";
import { PromptLegend } from "./PromptLegend";
import { ReplaceManualModal } from "./ReplaceManualModal";
import { ShotPromptEditor } from "./ShotPromptEditor";

type ShotPromptsPanelProps = {
  projectId: number;
};

const STATUS: Record<
  ShotPromptEntry["status"],
  { label: string; color: string }
> = {
  not_compiled: { label: "Not compiled", color: "gray" },
  compiled: { label: "Compiled", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

const FORMAT_LABELS: Record<string, string> = {
  reference: "Reference format (six parts)",
  generate: "Text format (three fields)",
};

type ShotRowProps = {
  entry: ShotPromptEntry;
  busy: boolean;
  onCompile: () => void;
  onFeedback: () => void;
  saving: boolean;
  saveError: unknown;
  onStartEdit: () => void;
  onSave: (pieces: Record<string, string>, done: () => void) => void;
};

/**
 * One shot: its status, why it is out of date, and the prompt it is generated with, which can be
 * edited by hand.
 */
function ShotRow({
  entry,
  busy,
  onCompile,
  onFeedback,
  saving,
  saveError,
  onStartEdit,
  onSave,
}: ShotRowProps) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const { shot, prompt, version, job } = entry;
  const status = STATUS[entry.status];
  const compiled = entry.status !== "not_compiled";
  // A prompt made before the pieces were kept has none to edit: compiling it again gives it some.
  const editable = prompt !== null && Object.keys(prompt.pieces).length > 0;

  return (
    <Stack gap={4}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge
          variant="outline"
          color="gray"
          miw={64}
          style={{ flexShrink: 0, textTransform: "none" }}
        >
          {shot.id}
        </Badge>
        <Stack gap={2} style={{ flexGrow: 1 }}>
          <Group gap="xs">
            <Badge variant="light" color={status.color}>
              {status.label}
            </Badge>
            {version !== null && (
              <PromptHoverCard jobId={version.job_id} source={version.source}>
                <Badge variant="light" style={{ cursor: "help" }}>
                  v{version.version}
                </Badge>
              </PromptHoverCard>
            )}
            <FeedbackBadge text={version?.feedback} />
            {prompt !== null && (
              <Badge
                variant="light"
                color="gray"
                style={{ textTransform: "none" }}
              >
                {prompt.word_count} words
              </Badge>
            )}
            {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
            <Text size="sm" style={{ wordBreak: "break-word" }}>
              {shot.description}
            </Text>
          </Group>
          {prompt !== null && (
            <Text size="xs" c="dimmed">
              {FORMAT_LABELS[prompt.format] ?? prompt.format}: {prompt.endpoint}
            </Text>
          )}
          {!entry.can_run && entry.blocked_reason !== null && (
            <Text size="xs" c="dimmed">
              {entry.blocked_reason}
            </Text>
          )}
          {entry.reasons.map((text) => (
            <Text key={text} size="xs" c="yellow.8">
              {text}
            </Text>
          ))}
          {job?.status === "failed" && (
            <Alert color="red" p="xs" title="The last compilation failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
        </Stack>
        <Group gap="xs" justify="flex-end" maw={420} style={{ flexShrink: 0 }}>
          {prompt !== null && (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? "Hide the prompt" : "Show the prompt"}
            </Button>
          )}
          {prompt !== null && (
            <Button
              size="compact-xs"
              variant="default"
              title={
                editable
                  ? undefined
                  : "This prompt was compiled before its pieces were kept. Compile it again to edit it."
              }
              disabled={
                !editable || !entry.can_run || busy || isJobActive(job) || editing
              }
              onClick={() => {
                onStartEdit();
                setOpen(false);
                setEditing(true);
              }}
            >
              Edit
            </Button>
          )}
          <Button
            size="compact-xs"
            variant="default"
            disabled={!entry.can_run || busy || editing}
            onClick={onCompile}
          >
            {compiled ? "Compile again" : "Compile"}
          </Button>
          {prompt !== null && (
            <Button
              size="compact-xs"
              variant="default"
              title="Write this prompt again, with a note from you for the prompt writer"
              disabled={!entry.can_run || busy || isJobActive(job) || editing}
              onClick={onFeedback}
            >
              Regenerate with feedback
            </Button>
          )}
        </Group>
      </Group>
      {editing && prompt !== null && (
        <Paper withBorder p="md" radius="sm">
          <ShotPromptEditor
            prompt={prompt}
            saving={saving}
            error={saveError}
            onSave={(pieces) => onSave(pieces, () => setEditing(false))}
            onCancel={() => setEditing(false)}
          />
        </Paper>
      )}
      {prompt !== null && !editing && (
        <Collapse expanded={open}>
          <Stack gap="sm" pt={4}>
            {prompt.warnings.map((text) => (
              <Text key={text} size="xs" c="yellow.8">
                {text}
              </Text>
            ))}
            <PromptLegend prompt={prompt} />
            <Code
              block
              style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}
            >
              {prompt.prompt}
            </Code>
          </Stack>
        </Collapse>
      )}
    </Stack>
  );
}

type SceneRowProps = {
  scene: SceneShotPrompts;
  busy: boolean;
  onCompileScene: () => void;
  onCompileShot: (shot: ShotPromptEntry) => void;
  onFeedbackShot: (shot: ShotPromptEntry) => void;
  saving: boolean;
  saveError: unknown;
  onStartEdit: () => void;
  onSave: (
    shotId: string,
    pieces: Record<string, string>,
    done: () => void,
  ) => void;
};

/** One scene: how many of its shots have a prompt, and its shots. */
function SceneRow({
  scene,
  busy,
  onCompileScene,
  onCompileShot,
  onFeedbackShot,
  saving,
  saveError,
  onStartEdit,
  onSave,
}: SceneRowProps) {
  const compiled = scene.shots.filter(
    (shot) => shot.status === "compiled",
  ).length;
  const outOfDate = scene.shots.filter(
    (shot) => shot.status === "out_of_date",
  ).length;
  // What "Compile scene" would do for this scene.
  const todo = scene.shots.filter(
    (shot) => shot.can_run && shot.status !== "compiled",
  ).length;

  return (
    <Stack gap={6}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge
          variant="outline"
          color="gray"
          miw={40}
          style={{ flexShrink: 0, textTransform: "none" }}
        >
          {scene.index}
        </Badge>
        <Group gap="xs" style={{ flexGrow: 1 }}>
          <Text size="sm" fw={500}>
            {scene.title}
          </Text>
          <Badge variant="light" color="gray">
            {compiled} of {scene.shots.length} compiled
          </Badge>
          {outOfDate > 0 && (
            <Badge variant="light" color="yellow">
              {outOfDate} out of date
            </Badge>
          )}
        </Group>
        <Button
          size="compact-sm"
          variant="default"
          disabled={busy || todo === 0}
          onClick={onCompileScene}
          style={{ flexShrink: 0 }}
        >
          Compile scene
        </Button>
      </Group>
      {scene.shots.length > 0 && (
        <Stack gap="sm" ml={48}>
          {scene.shots.map((entry) => (
            <ShotRow
              key={entry.shot.id}
              entry={entry}
              busy={busy}
              onCompile={() => onCompileShot(entry)}
              onFeedback={() => onFeedbackShot(entry)}
              saving={saving}
              saveError={saveError}
              onStartEdit={onStartEdit}
              onSave={(pieces, done) => onSave(entry.shot.id, pieces, done)}
            />
          ))}
        </Stack>
      )}
    </Stack>
  );
}

/**
 * The H3 prompts stage: for each shot with a planned request, the final prompt the video model
 * is given. A language model writes the creative pieces (the style, each subject, the summary,
 * the shot and the soundscape) and code writes everything else: the headings, the labels, the
 * lines that say how each picture and audio is used, who does not speak, and "N/A" for music.
 * A shot's prompt is compiled by itself when its request is planned, and can be edited by hand.
 */
export function ShotPromptsPanel({ projectId }: ShotPromptsPanelProps) {
  const { data, isLoading, isError, error } = useShotPrompts(projectId);
  const compileAll = useCompileAllPrompts(projectId);
  const compileScene = useCompileScenePrompts(projectId);
  const compileOne = useCompileOnePrompt(projectId);
  const save = useSaveShotPrompt(projectId);
  // The shot whose newest prompt the user wrote, waiting for "yes, compile it again".
  const [confirming, setConfirming] = useState<{
    sceneId: string;
    shotId: string;
  } | null>(null);
  // The shot the user is writing a note about.
  const [feedbackFor, setFeedbackFor] = useState<{
    sceneId: string;
    entry: ShotPromptEntry;
  } | null>(null);

  const entries = data?.entries ?? [];
  const busy =
    compileAll.isPending || compileScene.isPending || compileOne.isPending;
  const projectBlocked = (data?.blocked_reason ?? null) !== null;
  // What "Compile all" would do: the shots that may be compiled and have no current prompt.
  const allCount = entries.reduce(
    (sum, scene) =>
      sum +
      scene.shots.filter((shot) => shot.can_run && shot.status !== "compiled")
        .length,
    0,
  );
  // The shots the last press could not do, with why.
  const skipped = [
    ...(compileAll.data?.skipped ?? []),
    ...(compileScene.data?.skipped ?? []),
  ].filter(
    (item) => item.shot_id !== null && !item.reason.startsWith("Already"),
  );

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>H3 prompts</Title>
            <Text size="sm" c="dimmed">
              Writes the final prompt each shot is made from, with one model call
              per shot. The model writes the style, the descriptions, the shot
              and the soundscape; the labels, the lines that say how each
              picture and speech is used, and the music line (always off) are
              written by rule. A shot&apos;s prompt is compiled by itself when
              its request is planned.
            </Text>
          </Stack>
          <Button
            onClick={() => compileAll.mutate()}
            loading={compileAll.isPending}
            disabled={
              isLoading || isError || busy || projectBlocked || allCount === 0
            }
            style={{ flexShrink: 0 }}
          >
            Compile all
          </Button>
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the shot prompts">
            {describeError(error)}
          </Alert>
        )}
        {[compileAll, compileScene, compileOne].map(
          (mutation, position) =>
            mutation.isError && (
              <Alert
                key={position}
                color="red"
                title="Could not compile the prompts"
              >
                {describeError(mutation.error)}
              </Alert>
            ),
        )}
        {skipped.length > 0 && (
          <Alert color="blue" title="Not compiled">
            <Stack gap={2}>
              {skipped.map((item) => (
                <Text key={`${item.scene_id}/${item.shot_id}`} size="sm">
                  {item.title}, {item.shot_id}: {item.reason}
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
        {entries.length > 0 && <Divider />}

        {entries.map((scene) => (
          <SceneRow
            key={scene.id}
            scene={scene}
            busy={busy}
            onCompileScene={() => compileScene.mutate(scene.id)}
            onCompileShot={(shot) =>
              shot.needs_confirmation
                ? setConfirming({ sceneId: scene.id, shotId: shot.shot.id })
                : compileOne.mutate({
                    sceneId: scene.id,
                    shotId: shot.shot.id,
                    confirmReplaceManual: false,
                  })
            }
            onFeedbackShot={(entry) =>
              setFeedbackFor({ sceneId: scene.id, entry })
            }
            saving={save.isPending}
            saveError={save.error}
            onStartEdit={() => save.reset()}
            onSave={(shotId, pieces, done) =>
              save.mutate(
                { sceneId: scene.id, shotId, pieces },
                { onSuccess: done },
              )
            }
          />
        ))}
      </Stack>
      <FeedbackModal
        opened={feedbackFor !== null}
        title={`Feedback on the prompt of ${feedbackFor?.entry.shot.id ?? "this shot"}`}
        what="the prompt of this shot"
        initialText={feedbackFor?.entry.version?.feedback ?? ""}
        writtenByUser={feedbackFor?.entry.needs_confirmation ?? false}
        submitLabel="Write the prompt again"
        onCancel={() => setFeedbackFor(null)}
        onSubmit={(text) => {
          if (feedbackFor !== null) {
            compileOne.mutate({
              sceneId: feedbackFor.sceneId,
              shotId: feedbackFor.entry.shot.id,
              confirmReplaceManual: feedbackFor.entry.needs_confirmation,
              feedback: text,
            });
          }
          setFeedbackFor(null);
        }}
      />
      <ReplaceManualModal
        opened={confirming !== null}
        title="Compile this prompt again?"
        what={`The newest prompt of ${confirming?.shotId ?? "this shot"}`}
        confirmLabel="Compile again"
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          if (confirming !== null) {
            compileOne.mutate({ ...confirming, confirmReplaceManual: true });
          }
          setConfirming(null);
        }}
      />
    </Paper>
  );
}
