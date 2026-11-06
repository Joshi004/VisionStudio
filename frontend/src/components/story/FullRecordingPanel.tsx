import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  FileButton,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  PREVIEW_SPAN_S,
  recordingExcerptUrl,
  useDecideBoundary,
  useFullRecording,
  useKeepAllBoundaries,
  useRetryFullRecording,
  useRetryPatch,
  useSplicePatches,
  useUploadFullRecording,
  useUploadPatch,
  type FullRecordingState,
  type FullScript,
  type PatchRegion,
  type RecordingOrigin,
  type SceneBoundary,
} from "../../api/voiceRecordings";
import { BoundaryCutModal } from "./BoundaryCutModal";
import { FullRecordingModal } from "./FullRecordingModal";
import { PatchRecordingModal } from "./PatchRecordingModal";

type FullRecordingPanelProps = {
  projectId: number;
};

/** The files a recording may be: the server decides by what is inside, not by the name. */
const RECORDING_ACCEPT = ".wav,.mp3,.webm,.m4a,.mp4,audio/*";

const STAGE: Record<
  FullRecordingState["stage"],
  { label: string; color: string }
> = {
  transcribing: { label: "Being transcribed", color: "blue" },
  transcription_failed: { label: "Transcription failed", color: "red" },
  refused: { label: "Refused", color: "red" },
  tight: { label: "Tight scene boundaries", color: "yellow" },
  splitting: { label: "Being split into scenes", color: "blue" },
  split_failed: { label: "Not split", color: "red" },
  split: { label: "Split into scenes", color: "green" },
};

function formatLength(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** "Scene 3", from the script's own numbering. */
function sceneName(script: FullScript, sceneId: string): string {
  const position = script.scenes.findIndex(
    (scene) => scene.scene_id === sceneId,
  );
  if (position < 0) {
    return "a scene";
  }
  return `Scene ${script.scenes[position].index ?? position + 1}`;
}

const PATCH_STAGE: Record<
  NonNullable<PatchRegion["patch_stage"]>,
  { label: string; color: string }
> = {
  transcribing: { label: "Being transcribed", color: "blue" },
  transcription_failed: { label: "Transcription failed", color: "red" },
  refused: { label: "Refused", color: "red" },
  accepted: { label: "Accepted", color: "green" },
};

function regionKey(region: PatchRegion): string {
  return `${region.first_word}-${region.last_word}`;
}

/** "Scene 3 to Scene 4": the scene changes a part covers. */
function regionTitle(script: FullScript, region: PatchRegion): string {
  const first = region.boundaries[0];
  const last = region.boundaries[region.boundaries.length - 1];
  if (first === undefined || last === undefined) {
    return "this part";
  }
  return `${sceneName(script, first.after_scene_id)} to ${sceneName(
    script,
    last.before_scene_id,
  )}`;
}

/** The part of the recording that fixes a boundary, when it has one. */
function regionOf(
  newest: FullRecordingState,
  boundary: SceneBoundary,
): PatchRegion | undefined {
  return newest.regions.find((region) =>
    region.boundaries.some(
      (item) =>
        item.after_scene_id === boundary.after_scene_id &&
        item.before_scene_id === boundary.before_scene_id,
    ),
  );
}

type TightBoundaryCardProps = {
  projectId: number;
  recordingId: number;
  script: FullScript;
  boundary: SceneBoundary;
  /** False while the recording cannot take decisions (it is being split, for example). */
  canDecide: boolean;
  /** The part of the recording that fixes this boundary (REC-006), and whether it can be recorded. */
  region: PatchRegion | undefined;
  canPatch: boolean;
  onRecordPart: () => void;
};

/**
 * One tight scene boundary (REC-005): the words around it, a player for the two seconds either
 * side of where it is cut now, and the owner's choices: keep it as is (cut in the middle of the
 * pause), or set the cut point by hand. A decision can be changed later.
 */
function TightBoundaryCard({
  projectId,
  recordingId,
  script,
  boundary,
  canDecide,
  region,
  canPatch,
  onRecordPart,
}: TightBoundaryCardProps) {
  const decide = useDecideBoundary(projectId, recordingId);
  const [cutOpen, setCutOpen] = useState(false);
  const title = `${sceneName(script, boundary.after_scene_id)} to ${sceneName(
    script,
    boundary.before_scene_id,
  )}`;
  const badge =
    boundary.decision === null
      ? { label: "Not decided", color: "yellow" }
      : boundary.decision === "keep"
        ? { label: "Kept as is", color: "green" }
        : {
            label: `Cut at ${(boundary.decision_cut_s ?? boundary.final_cut_s).toFixed(3)} s`,
            color: "green",
          };

  return (
    <Paper withBorder p="xs" radius="sm">
      <Stack gap={4}>
        <Group gap="xs" align="center">
          <Text size="xs" fw={600}>
            {title}, pause {Math.round(boundary.pause_s * 1000)} ms
          </Text>
          <Badge variant="light" size="sm" color={badge.color}>
            {badge.label}
          </Badge>
        </Group>
        <Text size="xs">
          …{boundary.before_words}{" "}
          <Text span c="dimmed">
            |
          </Text>{" "}
          {boundary.after_words}…
        </Text>
        {boundary.reasons.map((reason) => (
          <Text key={reason} size="xs" c="yellow.8">
            {reason}
          </Text>
        ))}
        <audio
          controls
          preload="none"
          src={recordingExcerptUrl(
            projectId,
            recordingId,
            Math.max(0, boundary.final_cut_s - PREVIEW_SPAN_S),
            boundary.final_cut_s + PREVIEW_SPAN_S,
          )}
          style={{ width: "100%", height: 32 }}
        />
        <Group gap="xs">
          <Button
            size="compact-xs"
            variant="default"
            loading={decide.isPending && decide.variables?.decision === "keep"}
            disabled={
              !canDecide || decide.isPending || boundary.decision === "keep"
            }
            onClick={() =>
              decide.mutate({
                afterSceneId: boundary.after_scene_id,
                beforeSceneId: boundary.before_scene_id,
                decision: "keep",
              })
            }
          >
            Keep as is
          </Button>
          <Button
            size="compact-xs"
            variant="default"
            disabled={!canDecide || decide.isPending}
            onClick={() => {
              decide.reset();
              setCutOpen(true);
            }}
          >
            Set the cut point
          </Button>
          <Button
            size="compact-xs"
            variant="default"
            disabled={!canPatch || region === undefined}
            onClick={onRecordPart}
          >
            Record this part
          </Button>
        </Group>
        {region?.patch_stage != null && region.patch_message != null && (
          <Text
            size="xs"
            c={region.patch_stage === "accepted" ? "green.8" : "dimmed"}
          >
            {PATCH_STAGE[region.patch_stage].label}: {region.patch_message}
          </Text>
        )}
        {decide.isError && !cutOpen && (
          <Alert color="red" title="Could not save the decision">
            {describeError(decide.error)}
          </Alert>
        )}
      </Stack>
      <BoundaryCutModal
        opened={cutOpen}
        onClose={() => setCutOpen(false)}
        projectId={projectId}
        recordingId={recordingId}
        boundary={boundary}
        title={title}
        saving={decide.isPending}
        error={decide.error}
        onSave={(cutS) =>
          decide.mutate(
            {
              afterSceneId: boundary.after_scene_id,
              beforeSceneId: boundary.before_scene_id,
              decision: "cut_at",
              cutS,
            },
            { onSuccess: () => setCutOpen(false) },
          )
        }
      />
    </Paper>
  );
}

type TightBoundariesProps = {
  projectId: number;
  script: FullScript;
  newest: FullRecordingState;
};

type PartRowProps = {
  script: FullScript;
  region: PatchRegion;
  canPatch: boolean;
  uploading: boolean;
  retrying: boolean;
  onRecord: () => void;
  onUpload: (file: File) => void;
  onRetry: (patchId: number) => void;
};

/** One part to record again (REC-006), with the state of the newest patch recorded for it. */
function PartRow({
  script,
  region,
  canPatch,
  uploading,
  retrying,
  onRecord,
  onUpload,
  onRetry,
}: PartRowProps) {
  return (
    <Paper withBorder p="xs" radius="sm">
      <Stack gap={4}>
        <Group gap="xs" align="center">
          <Text size="xs" fw={600}>
            {regionTitle(script, region)}
          </Text>
          {region.patch_stage != null && (
            <Badge
              variant="light"
              size="sm"
              color={PATCH_STAGE[region.patch_stage].color}
            >
              {PATCH_STAGE[region.patch_stage].label}
            </Badge>
          )}
        </Group>
        <Text size="xs" lineClamp={2}>
          {region.parts.join(" | ")}
        </Text>
        {region.patch_message != null && (
          <Text
            size="xs"
            c={
              region.patch_stage === "refused" ||
              region.patch_stage === "transcription_failed"
                ? "red"
                : "dimmed"
            }
          >
            {region.patch_message}
          </Text>
        )}
        <Group gap="xs">
          <Button size="compact-xs" disabled={!canPatch} onClick={onRecord}>
            {region.patch_id === null ? "Record this part" : "Record it again"}
          </Button>
          <FileButton
            onChange={(file) => {
              if (file !== null) {
                onUpload(file);
              }
            }}
            accept={RECORDING_ACCEPT}
          >
            {(props) => (
              <Button
                {...props}
                size="compact-xs"
                variant="default"
                loading={uploading}
                disabled={!canPatch}
              >
                Upload this part
              </Button>
            )}
          </FileButton>
          {region.patch_stage === "transcription_failed" &&
            region.patch_id !== null && (
              <Button
                size="compact-xs"
                variant="default"
                loading={retrying}
                disabled={!canPatch}
                onClick={() => onRetry(region.patch_id as number)}
              >
                Try again
              </Button>
            )}
        </Group>
      </Stack>
    </Paper>
  );
}

/**
 * Every tight boundary of the newest full recording, with "Keep all as is" while any is
 * undecided (REC-005). They stay listed once decided, and after the split, so that a decision
 * can be changed: a changed decision splits again, and only the two scenes either side of that
 * cut get new takes.
 *
 * A tight boundary can also be fixed by recording a short part of the text again (REC-006). The
 * parts are listed together, so they can all be recorded in one sitting; each is transcribed and
 * checked on its own, and "Splice in N patches" makes one new version of the recording that holds
 * every accepted part.
 */
function TightBoundaries({ projectId, script, newest }: TightBoundariesProps) {
  const keepAll = useKeepAllBoundaries(projectId, newest.recording_id);
  const sendPatch = useUploadPatch(projectId, newest.recording_id);
  const sendFile = useUploadPatch(projectId, newest.recording_id);
  const splice = useSplicePatches(projectId, newest.recording_id);
  const retryPatch = useRetryPatch(projectId, newest.recording_id);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const tight = newest.boundaries.filter((boundary) => boundary.tight);
  // A fast reader leaves little pause: recording again with a clear pause is the better fix.
  const mostlyTight = tight.length * 2 > newest.boundaries.length;
  const openRegion =
    newest.regions.find((region) => regionKey(region) === openKey) ?? null;
  const count = newest.accepted_patch_count;

  function send(
    region: PatchRegion,
    origin: RecordingOrigin,
    file: Blob,
    done?: () => void,
  ) {
    const mutation = origin === "upload" ? sendFile : sendPatch;
    mutation.mutate(
      {
        firstWord: region.first_word,
        lastWord: region.last_word,
        origin,
        file,
      },
      { onSuccess: done },
    );
  }

  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed">
        A tight boundary has too little pause to cut at, or a word next to it
        was not heard. For each one, keep the cut in the middle of the pause,
        set the cut point yourself, or record the part around it again. A
        recording that is cut where it should not be can also be recorded again
        with a clear pause at the scene changes.
      </Text>
      {mostlyTight && (
        <Text size="xs" c="yellow.8">
          Most of the scene changes are tight. It is probably quicker to record
          the whole video again and pause clearly at every pause sign.
        </Text>
      )}
      {newest.open_count > 0 && (
        <Group>
          <Button
            size="compact-xs"
            loading={keepAll.isPending}
            disabled={!newest.can_decide}
            onClick={() => keepAll.mutate()}
          >
            Keep all as is
          </Button>
        </Group>
      )}
      {keepAll.isError && (
        <Alert color="red" title="Could not keep the boundaries">
          {describeError(keepAll.error)}
        </Alert>
      )}
      {tight.map((boundary) => {
        const region = regionOf(newest, boundary);
        return (
          <TightBoundaryCard
            key={`${boundary.after_scene_id}/${boundary.before_scene_id}`}
            projectId={projectId}
            recordingId={newest.recording_id}
            script={script}
            boundary={boundary}
            canDecide={newest.can_decide}
            region={region}
            canPatch={newest.can_patch}
            onRecordPart={() => {
              sendPatch.reset();
              sendFile.reset();
              setOpenKey(region === undefined ? null : regionKey(region));
            }}
          />
        );
      })}
      {newest.regions.length > 0 && (
        <Stack gap="xs">
          <Text size="xs" fw={600}>
            Parts to record again
          </Text>
          <Text size="xs" c="dimmed">
            Each part replaces the stretch of the recording between two pauses
            around a scene change. Record them all, then splice them in
            together.
          </Text>
          {newest.regions.map((region) => (
            <PartRow
              key={regionKey(region)}
              script={script}
              region={region}
              canPatch={newest.can_patch}
              uploading={sendFile.isPending}
              retrying={retryPatch.isPending}
              onRecord={() => {
                sendPatch.reset();
                sendFile.reset();
                setOpenKey(regionKey(region));
              }}
              onUpload={(file) => send(region, "upload", file)}
              onRetry={(patchId) => retryPatch.mutate(patchId)}
            />
          ))}
          {sendFile.isError && (
            <Alert color="red" title="Could not use the file">
              {describeError(sendFile.error)}
            </Alert>
          )}
          {retryPatch.isError && (
            <Alert color="red" title="Could not try again">
              {describeError(retryPatch.error)}
            </Alert>
          )}
          <Group gap="xs" align="center">
            <Button
              size="compact-xs"
              loading={splice.isPending || newest.splice_stage === "splicing"}
              disabled={!newest.can_splice}
              onClick={() => splice.mutate()}
            >
              {`Splice in ${count} ${count === 1 ? "patch" : "patches"}`}
            </Button>
            <Text size="xs" c="dimmed">
              {count === 0
                ? "No part is accepted yet."
                : `${count} ${count === 1 ? "part is" : "parts are"} accepted.`}
            </Text>
          </Group>
          {newest.splice_stage === "splicing" && (
            <Text size="xs" c="dimmed">
              The parts are being spliced into a new version of the recording.
            </Text>
          )}
          {newest.splice_stage === "splice_failed" && (
            <Text size="xs" c="red">
              The parts could not be spliced in: {newest.splice_error}
            </Text>
          )}
          {splice.isError && (
            <Alert color="red" title="Could not splice the parts">
              {describeError(splice.error)}
            </Alert>
          )}
        </Stack>
      )}
      {openRegion !== null && (
        <PatchRecordingModal
          opened
          onClose={() => setOpenKey(null)}
          region={openRegion}
          title={regionTitle(script, openRegion)}
          sending={sendPatch.isPending || sendFile.isPending}
          error={sendPatch.error ?? sendFile.error}
          onSend={(recording) =>
            send(openRegion, "browser", recording, () => setOpenKey(null))
          }
          onUpload={(file) =>
            send(openRegion, "upload", file, () => setOpenKey(null))
          }
        />
      )}
    </Stack>
  );
}

/**
 * Recording the whole video in one flow (REC-004): the person records it in the browser or
 * uploads a file, the app transcribes it, finds the scene boundaries and, once every tight
 * boundary is decided (REC-005), splits it into one take for each scene. This panel shows where
 * the newest full recording stands and lists the tight boundaries, to keep or to cut by hand.
 */
export function FullRecordingPanel({ projectId }: FullRecordingPanelProps) {
  const { data, isLoading, isError, error } = useFullRecording(projectId, true);
  // Two mutations so that each one's error shows where the person is looking.
  const sendFile = useUploadFullRecording(projectId);
  const sendRecording = useUploadFullRecording(projectId);
  const retry = useRetryFullRecording(projectId);
  const [recordingOpen, setRecordingOpen] = useState(false);

  const sending = sendFile.isPending || sendRecording.isPending;
  const script = data?.script;
  const newest = data?.newest ?? null;
  const canRecord =
    script !== undefined && script.blocked_reason === null && !sending;

  function send(origin: RecordingOrigin, file: Blob, done?: () => void) {
    if (script === undefined) {
      return;
    }
    const mutation = origin === "upload" ? sendFile : sendRecording;
    mutation.mutate(
      { scriptKey: script.script_key, origin, file },
      { onSuccess: done },
    );
  }

  return (
    <Paper withBorder p="sm" radius="sm">
      <Stack gap="xs">
        <Text fw={600} size="sm">
          Record the whole video
        </Text>
        <Text size="xs" c="dimmed">
          Read the whole script in one go, in the browser or from a file. The
          app finds where each scene begins from your pauses and cuts the
          recording into one take for each scene. Or record scene by scene
          below.
        </Text>
        {isLoading && <Loader size="xs" />}
        {isError && (
          <Alert color="red" title="Could not load the full recording">
            {describeError(error)}
          </Alert>
        )}
        {script?.blocked_reason != null && (
          <Text size="xs" c="dimmed">
            {script.blocked_reason}
          </Text>
        )}
        <Group gap="xs">
          <Button
            size="compact-sm"
            disabled={!canRecord}
            onClick={() => {
              sendRecording.reset();
              setRecordingOpen(true);
            }}
          >
            {newest === null ? "Record the whole video" : "Record it again"}
          </Button>
          <FileButton
            onChange={(file) => {
              if (file !== null) {
                send("upload", file);
              }
            }}
            accept={RECORDING_ACCEPT}
          >
            {(props) => (
              <Button
                {...props}
                size="compact-sm"
                variant="default"
                loading={sendFile.isPending}
                disabled={!canRecord}
              >
                Upload the whole video
              </Button>
            )}
          </FileButton>
        </Group>
        {sendFile.isError && (
          <Alert color="red" title="Could not use the file">
            {describeError(sendFile.error)}
          </Alert>
        )}
        {retry.isError && (
          <Alert color="red" title="Could not try again">
            {describeError(retry.error)}
          </Alert>
        )}
        {newest !== null && script !== undefined && (
          <Stack gap={4}>
            <Group gap="xs" align="center">
              <Badge variant="light" color={STAGE[newest.stage].color}>
                {STAGE[newest.stage].label}
              </Badge>
              <Text size="xs" c="dimmed">
                Version {newest.version}, {formatLength(newest.duration_s)}
              </Text>
              {newest.can_retry && (
                <Button
                  size="compact-xs"
                  variant="default"
                  loading={retry.isPending}
                  onClick={() => retry.mutate(newest.recording_id)}
                >
                  {newest.stage === "split_failed" ? "Split now" : "Try again"}
                </Button>
              )}
            </Group>
            {newest.stage !== "split" && (
              <Text
                size="xs"
                c={
                  newest.stage === "transcribing" ||
                  newest.stage === "splitting"
                    ? "dimmed"
                    : "red"
                }
              >
                {newest.message}
              </Text>
            )}
            {newest.script_changed && (
              <Text size="xs" c="yellow.8">
                The script was changed after this was recorded. A scene whose
                text changed has to be recorded again.
              </Text>
            )}
            {newest.tight_count > 0 && (
              <TightBoundaries
                projectId={projectId}
                script={script}
                newest={newest}
              />
            )}
          </Stack>
        )}
      </Stack>
      {script !== undefined && (
        <FullRecordingModal
          opened={recordingOpen}
          onClose={() => setRecordingOpen(false)}
          script={script}
          sending={sendRecording.isPending}
          error={sendRecording.error}
          onSend={(recording) =>
            send("browser", recording, () => setRecordingOpen(false))
          }
        />
      )}
    </Paper>
  );
}
