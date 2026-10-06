import { useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";

import { useGenerateClip, useGenerateReadyScenes } from "../../api/clips";
import { describeError } from "../../api/errors";
import type { ProjectDetail } from "../../api/projects";
import { useProposeScenes, useScenes, type Scene } from "../../api/scenes";
import { useTranscription } from "../../api/transcription";
import { formatDateTime } from "../../format";
import { JobActions } from "../jobs/JobActions";
import { elapsedText, statusColor, typicalText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { clipCell, generateLabel, hasActiveClipJob } from "./clipView";
import { CutEditor } from "./CutEditor";
import { missingText } from "./promptHints";
import { SceneInputsDrawer } from "./SceneInputsDrawer";
import { useScenePlayer } from "./scenePlayer";
import {
  checksLine,
  isOutsideLimits,
  llmHost,
  seconds,
  staleSceneMessage,
  usageLine,
} from "./sceneView";

const CUT_SOURCE_LABELS: Record<Scene["cut_source"], { label: string; color: string }> = {
  ai: { label: "AI", color: "blue" },
  rule: { label: "Rule", color: "grape" },
  manual: { label: "Manual", color: "gray" },
};

type PendingConfirmation = { runAgain: boolean };

export function ScenesSection({ project }: { project: ProjectDetail }) {
  const scenesQuery = useScenes(project.id);
  // The transcript query is shared with the transcript section: one request, one cache entry.
  const transcription = useTranscription(project.id);
  const propose = useProposeScenes(project.id);
  const generateClip = useGenerateClip(project.id);
  const generateAll = useGenerateReadyScenes(project.id);
  const { audioRef, playingId, play, stop, onTimeUpdate, onPause, onEnded } = useScenePlayer();
  const [pending, setPending] = useState<PendingConfirmation | null>(null);
  const [confirmingAll, setConfirmingAll] = useState(false);
  const [editing, setEditing] = useState(false);
  // The scene whose inputs are open in the drawer, and whether the list of what is missing shows.
  const [inputsSceneId, setInputsSceneId] = useState<number | null>(null);
  const [showMissing, setShowMissing] = useState(false);

  const { data, isLoading, isError, error, dataUpdatedAt } = scenesQuery;
  // Elapsed times are worked out from the stored times as of the last time the data was
  // loaded (on page load, Refresh or returning to the tab). There is no timer.
  const now = dataUpdatedAt;

  const job = data?.job ?? null;
  const proposal = data?.proposal ?? null;
  const scenes = data?.scenes ?? [];
  const transcript = transcription.data?.transcript ?? null;
  const isActive = job !== null && (job.status === "queued" || job.status === "running");
  const hasScript = project.script_text !== null && project.script_text.trim() !== "";

  const mismatchWarnings = transcript?.warnings ?? [];
  const scenesWithInputs = scenes.filter((scene) => scene.has_inputs).length;

  // Cuts can be edited while the scenes are current and no proposal is running. The server
  // says why not (data.edit_blocked_reason), and the answer to every edit carries it again.
  const editBlockedReason = data?.edit_blocked_reason ?? null;
  const showEditor = editing && data !== undefined && editBlockedReason === null;

  let blockedReason: string | null = null;
  if (!project.voiceover) {
    blockedReason = "Upload a voiceover first.";
  } else if (!hasScript) {
    blockedReason = "Paste the script first.";
  } else if (!transcript) {
    blockedReason = "Transcribe the voiceover first.";
  } else if (transcript.stale_reasons.length > 0) {
    blockedReason = "The transcript is out of date. Transcribe again first.";
  } else if (isActive) {
    blockedReason = "A proposal is already in progress.";
  }

  function click(runAgain: boolean) {
    // The two questions the page asks before a paid call that replaces something.
    if (mismatchWarnings.length > 0 || scenesWithInputs > 0) {
      setPending({ runAgain });
      return;
    }
    propose.mutate({
      run_again: runAgain,
      accept_mismatch: false,
      discard_scenes_with_inputs: false,
    });
  }

  function confirm() {
    if (pending === null) {
      return;
    }
    propose.mutate({
      run_again: pending.runAgain,
      accept_mismatch: mismatchWarnings.length > 0,
      discard_scenes_with_inputs: scenesWithInputs > 0,
    });
    setPending(null);
  }

  const usage = proposal ? usageLine(proposal) : null;
  const checks = proposal ? checksLine(proposal) : null;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Title order={4}>Scenes</Title>
          <Group gap="sm">
            {blockedReason && (
              <Text size="xs" c="dimmed">
                {blockedReason}
              </Text>
            )}
            {proposal && (
              <Button
                variant="default"
                onClick={() => click(true)}
                disabled={blockedReason !== null}
                loading={propose.isPending}
              >
                Run again
              </Button>
            )}
            <Button
              onClick={() => click(false)}
              disabled={blockedReason !== null}
              loading={propose.isPending}
            >
              Propose scenes
            </Button>
          </Group>
        </Group>

        {data && (
          <Text size="xs" c="dimmed">
            Calls the language model ({data.llm.model} at {llmHost(data.llm.will_call)}): a paid
            call that sends your script and its word times. Propose scenes reuses the stored
            answer when nothing has changed. Run again always asks the model again.
          </Text>
        )}

        {isLoading && <Loader size="sm" />}

        {isError && (
          <Alert color="red" title="Could not load the scenes">
            {describeError(error)} Press Refresh to try again.
          </Alert>
        )}

        {propose.isError && (
          <Alert color="red" title="The proposal was not started">
            {describeError(propose.error)}
          </Alert>
        )}

        {job && (
          <Stack gap={4}>
            <Group gap="sm">
              <JobStatusBadge job={job} />
              <Text size="sm" c="dimmed">
                {elapsedText(job, now)}
              </Text>
              <JobActions job={job} />
            </Group>
            {isActive && (
              <Text size="xs" c="dimmed">
                A proposal takes about 20 seconds. Press Refresh to see its progress.
              </Text>
            )}
          </Stack>
        )}

        {job?.status === "failed" && job.error && (
          <Alert color="red" title="The proposal failed">
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {job.error}
            </Text>
          </Alert>
        )}

        {data && !job && scenes.length === 0 && (
          <Text c="dimmed">
            No scenes yet. Proposing splits the script into scenes of {project.min_scene_seconds}{" "}
            to {project.max_scene_seconds} seconds.
          </Text>
        )}

        {data && data.stale_reasons.length > 0 && (
          <Alert color="yellow" title="These scenes are out of date">
            {data.stale_reasons.map((reason) => (
              <Text key={reason} size="sm">
                {staleSceneMessage(reason)}
              </Text>
            ))}
            <Text size="sm">
              Transcribe again if needed, then propose scenes to replace them.
            </Text>
          </Alert>
        )}

        {proposal?.source === "rule" && (
          <Alert color="orange" title="The rule-based splitter proposed these scenes">
            <Text size="sm">
              The language model could not be used, so the cuts come from the script's paragraph
              breaks and punctuation alone.
            </Text>
            {proposal.fallback_reason && (
              <Text size="sm" style={{ wordBreak: "break-word" }}>
                Reason: {proposal.fallback_reason}
              </Text>
            )}
          </Alert>
        )}

        {proposal && scenes.length > 0 && (
          <Stack gap={2}>
            <Text size="sm" c="dimmed">
              {scenes.length} scenes · proposed {proposal.finished_at ? formatDateTime(proposal.finished_at) : ""}
              {proposal.source === "ai" ? " by the language model" : " by the rule-based splitter"}
            </Text>
            {proposal.cache_hit_of_job_id !== null && (
              <Text size="xs" c="dimmed">
                Reused the stored answer from job {proposal.cache_hit_of_job_id}: no call was made.
              </Text>
            )}
            {usage && (
              <Text size="xs" c="dimmed">
                {usage}
              </Text>
            )}
            {checks && (
              <Text size="xs" c="dimmed">
                {checks}
              </Text>
            )}
          </Stack>
        )}

        {scenes.length > 0 && data && (
          <>
            <Stack gap={4}>
              <Group gap="sm" align="center">
                <Text size="sm" fw={600}>
                  {data.ready_count} of {scenes.length} scenes ready
                </Text>
                {data.ready_count < scenes.length && (
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    onClick={() => setShowMissing(!showMissing)}
                  >
                    {showMissing ? "Hide what is missing" : "Show what is missing"}
                  </Button>
                )}
              </Group>
              <Group gap="sm" align="center">
                <Button
                  size="xs"
                  disabled={data.generate_ready_count === 0}
                  loading={generateAll.isPending}
                  onClick={() => setConfirmingAll(true)}
                >
                  Generate all ready scenes ({data.generate_ready_count})
                </Button>
                <Text size="xs" c="dimmed">
                  Starts a clip for each ready scene that has none yet. Each takes 5 to 10 minutes
                  on the GPU server, and at most {data.max_parallel_generations} run at once. Press
                  Refresh to see progress.
                </Text>
              </Group>
              {generateAll.isError && (
                <Alert color="red" title="The clips were not started">
                  {describeError(generateAll.error)}
                </Alert>
              )}
              {generateAll.isSuccess && (
                <Text size="xs" c="dimmed">
                  {generateAll.data.created === 0
                    ? "No clip needed to start."
                    : `Started ${generateAll.data.created} ${generateAll.data.created === 1 ? "clip" : "clips"}.`}
                </Text>
              )}
              {showMissing && data.ready_count < scenes.length && (
                <ScrollArea.Autosize mah={160} type="auto">
                  <Stack gap={2}>
                    {scenes
                      .filter((scene) => !scene.ready)
                      .map((scene) => (
                        <Text key={scene.id} size="xs">
                          <Anchor
                            component="button"
                            type="button"
                            size="xs"
                            onClick={() => setInputsSceneId(scene.id)}
                          >
                            Scene {scene.index + 1}
                          </Anchor>
                          : {missingText(scene.missing)}
                        </Text>
                      ))}
                  </Stack>
                </ScrollArea.Autosize>
              )}
            </Stack>
            <Group gap="sm" align="center">
              <Button
                size="xs"
                variant={showEditor ? "filled" : "default"}
                disabled={editBlockedReason !== null}
                onClick={() => setEditing(!editing)}
              >
                {showEditor ? "Done" : "Edit cuts"}
              </Button>
              {editBlockedReason !== null && (
                <Text size="xs" c="dimmed">
                  {editBlockedReason}
                </Text>
              )}
            </Group>
            {showEditor && data && (
              <CutEditor project={project} scenes={scenes} words={data.words} onEdited={stop} />
            )}
            {project.voiceover && (
              // Keyed by the asset, so a replacement voiceover loads fresh. It has no controls:
              // the Play buttons below drive it.
              <audio
                key={project.voiceover.asset_id}
                ref={audioRef}
                src={project.voiceover.url}
                preload="metadata"
                onTimeUpdate={onTimeUpdate}
                onPause={onPause}
                onEnded={onEnded}
              />
            )}
            <ScrollArea.Autosize mah={560} type="auto">
              <Table verticalSpacing="xs" stickyHeader>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>#</Table.Th>
                    <Table.Th>Time</Table.Th>
                    <Table.Th>Length</Table.Th>
                    <Table.Th>Text</Table.Th>
                    <Table.Th>Cut</Table.Th>
                    <Table.Th>Inputs</Table.Th>
                    <Table.Th style={{ minWidth: 170 }}>Clip</Table.Th>
                    <Table.Th />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {scenes.map((scene) => {
                    const length = scene.end_s - scene.start_s;
                    const outside = isOutsideLimits(
                      length,
                      project.min_scene_seconds,
                      project.max_scene_seconds,
                    );
                    const source = CUT_SOURCE_LABELS[scene.cut_source];
                    const isPlaying = playingId === scene.id;
                    return (
                      <Table.Tr key={scene.id}>
                        <Table.Td>{scene.index + 1}</Table.Td>
                        <Table.Td style={{ whiteSpace: "nowrap" }}>
                          {seconds(scene.start_s)} – {seconds(scene.end_s)} s
                        </Table.Td>
                        <Table.Td style={{ whiteSpace: "nowrap" }}>
                          {outside ? (
                            <Tooltip
                              label={`Outside the project's limits (${project.min_scene_seconds} to ${project.max_scene_seconds} s)`}
                            >
                              <Text size="sm" c="red" fw={600} component="span">
                                {seconds(length)} s
                              </Text>
                            </Tooltip>
                          ) : (
                            <Text size="sm" component="span">
                              {seconds(length)} s
                            </Text>
                          )}
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm">{scene.text}</Text>
                        </Table.Td>
                        <Table.Td>
                          <Stack gap={2} align="flex-start">
                            <Badge color={source.color} variant="light">
                              {source.label}
                            </Badge>
                            {scene.cut_note && (
                              <Text size="xs" c="orange.8">
                                {scene.cut_note}
                              </Text>
                            )}
                          </Stack>
                        </Table.Td>
                        <Table.Td>
                          <Stack gap={2} align="flex-start">
                            {scene.ready ? (
                              <Badge color="green" variant="light">
                                Ready
                              </Badge>
                            ) : (
                              <Text size="xs" c="dimmed">
                                Needs {missingText(scene.missing)}
                              </Text>
                            )}
                            <Button
                              size="compact-xs"
                              variant="default"
                              onClick={() => setInputsSceneId(scene.id)}
                            >
                              Inputs
                            </Button>
                          </Stack>
                        </Table.Td>
                        <Table.Td>
                          <Stack gap={2} align="flex-start">
                            {scene.clip_job !== null && hasActiveClipJob(scene) ? (
                              <>
                                <Badge color={statusColor(scene.clip_job.status)} variant="light">
                                  {scene.clip_job.status}
                                </Badge>
                                {scene.clip_job.phase && (
                                  <Text size="xs" c="dimmed">
                                    {scene.clip_job.phase}
                                  </Text>
                                )}
                                <Text size="xs" c="dimmed">
                                  {elapsedText(scene.clip_job, now)}
                                  {typicalText(scene.clip_typical_run_seconds) !== ""
                                    ? ` · ${typicalText(scene.clip_typical_run_seconds)}`
                                    : ""}
                                </Text>
                              </>
                            ) : (
                              <>
                                {scene.clip_job?.status === "failed" && (
                                  <Tooltip label={scene.clip_job.error ?? "The clip failed."}>
                                    <Badge color="red" variant="light">
                                      failed
                                    </Badge>
                                  </Tooltip>
                                )}
                                <Text size="xs" c="dimmed">
                                  {clipCell(scene)}
                                </Text>
                              </>
                            )}
                            <Group gap={4}>
                              <Tooltip
                                label={scene.generate_blocked_reason}
                                disabled={scene.generate_blocked_reason === null}
                                multiline
                                w={260}
                              >
                                <span>
                                  <Button
                                    size="compact-xs"
                                    variant="default"
                                    disabled={scene.generate_blocked_reason !== null}
                                    loading={
                                      generateClip.isPending &&
                                      generateClip.variables?.sceneId === scene.id
                                    }
                                    onClick={() => generateClip.mutate({ sceneId: scene.id })}
                                  >
                                    {generateLabel(scene)}
                                  </Button>
                                </span>
                              </Tooltip>
                              {scene.clip_job !== null && <JobActions job={scene.clip_job} />}
                            </Group>
                          </Stack>
                        </Table.Td>
                        <Table.Td>
                          <Button
                            size="compact-xs"
                            variant={isPlaying ? "filled" : "light"}
                            onClick={() => (isPlaying ? stop() : play(scene))}
                          >
                            {isPlaying ? "Stop" : "Play"}
                          </Button>
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </ScrollArea.Autosize>
          </>
        )}
      </Stack>

      <SceneInputsDrawer
        project={project}
        scenes={scenes}
        sceneId={inputsSceneId}
        now={now}
        onSelect={setInputsSceneId}
        onClose={() => setInputsSceneId(null)}
      />

      <Modal
        opened={confirmingAll}
        onClose={() => setConfirmingAll(false)}
        title="Generate all ready scenes"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Start {data?.generate_ready_count ?? 0}{" "}
            {data?.generate_ready_count === 1 ? "clip generation" : "clip generations"}? Each one
            uses a GPU on your server for about 5 to 10 minutes, and at most{" "}
            {data?.max_parallel_generations ?? 0} run at once. Scenes that already have a clip are
            skipped.
          </Text>
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setConfirmingAll(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                setConfirmingAll(false);
                generateAll.mutate();
              }}
            >
              Start
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={pending !== null}
        onClose={() => setPending(null)}
        title="Before the language model is called"
        centered
      >
        <Stack gap="sm">
          {mismatchWarnings.length > 0 && (
            <Alert color="orange" title="The recording differs from the script">
              {mismatchWarnings.map((warning) => (
                <Text key={warning} size="sm">
                  {warning}
                </Text>
              ))}
              <Text size="sm">You can fix the script and transcribe again, or go on anyway.</Text>
            </Alert>
          )}
          {scenesWithInputs > 0 && (
            <Alert color="yellow" title="Scenes with inputs will be replaced">
              <Text size="sm">
                {scenesWithInputs} of the {scenes.length} scenes{" "}
                {scenesWithInputs === 1 ? "has" : "have"} a description, frames or a clip.
                Proposing replaces all the scenes and discards those inputs. Their files stay on
                disk.
              </Text>
            </Alert>
          )}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setPending(null)}>
              Cancel
            </Button>
            <Button onClick={confirm}>Continue</Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
}
