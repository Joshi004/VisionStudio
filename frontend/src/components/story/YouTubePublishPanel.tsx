import { useCallback, useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Group,
  List,
  Loader,
  Modal,
  Paper,
  Progress,
  Radio,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { Link } from "react-router";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import { useThumbnails } from "../../api/thumbnails";
import {
  useDraftForYouTube,
  useRetryYouTubeUpload,
  useSaveYouTubeDraft,
  useSendYouTubeStep,
  useUploadToYouTube,
  useYouTubePanel,
  type YouTubeDraft,
  type YouTubePanel,
  type YouTubePrivacy,
  type YouTubeRetryRequest,
  type YouTubeSendRequest,
  type YouTubeUpload,
} from "../../api/youtube";
import { formatBytes, formatDateTime } from "../../format";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { YouTubeDraftEditor } from "./YouTubeDraftEditor";
import { YouTubeThumbnailsSection } from "./YouTubeThumbnailsSection";

type YouTubePublishPanelProps = {
  projectId: number;
};

const PRIVACY_OPTIONS: { value: YouTubePrivacy; label: string }[] = [
  { value: "private", label: "Private" },
  { value: "unlisted", label: "Unlisted" },
  { value: "public", label: "Public" },
];

type Answer = "yes" | "no";

/** The owner's answers to the two declarations, for one version of the draft. */
type Answers = { version: number | null; kids: Answer; synthetic: Answer };

// The declarations start at "Made for kids: No" and "Contains realistic AI content: Yes" (F-2).
// The owner can change either one; a new version of the draft starts at these again.
const DEFAULT_ANSWERS: Answers = {
  version: null,
  kids: "no",
  synthetic: "yes",
};

// The Select's value for the render that is being made now (the others are render numbers).
const RENDERING_VALUE = "rendering";

/**
 * Publishing a finished render to YouTube. The app writes a draft (title, description, hashtags,
 * tags) and a thumbnail; the owner edits everything, picks the channel and visibility, and may
 * change the two declarations, which start at No and Yes. Upload is disabled with its reason
 * until the rest is done, asks for a confirmation, and sends the render; the Uploads card
 * follows each upload, including the thumbnail and the captions that are sent once YouTube has
 * processed the video.
 */
export function YouTubePublishPanel({ projectId }: YouTubePublishPanelProps) {
  const [renderNumber, setRenderNumber] = useState<number | null>(null);
  const { data, isLoading, isError, error } = useYouTubePanel(
    projectId,
    renderNumber,
  );
  const thumbnails = useThumbnails(projectId);
  const draftRun = useDraftForYouTube(projectId);
  const save = useSaveYouTubeDraft(projectId);
  const [note, setNote] = useState("");
  const upload = useUploadToYouTube(projectId);
  const retry = useRetryYouTubeUpload(projectId);
  const send = useSendYouTubeStep(projectId);
  const [confirmOwn, setConfirmOwn] = useState(false);
  const [confirmUpload, setConfirmUpload] = useState(false);
  const [notify, setNotify] = useState(true);
  // The owner's choice for the captions box, kept with the render it was made for.
  const [captionsChoice, setCaptionsChoice] = useState<{
    renderNumber: number;
    value: boolean;
  } | null>(null);
  const [dirty, setDirty] = useState(false);
  const [answers, setAnswers] = useState<Answers>(DEFAULT_ANSWERS);
  const [channelChoice, setChannelChoice] = useState<string | null>(null);
  const [privacyChoice, setPrivacyChoice] = useState<YouTubePrivacy | null>(
    null,
  );
  const onDirtyChange = useCallback((value: boolean) => setDirty(value), []);

  const draft = data?.draft ?? null;
  const selected = data?.renders.find(
    (render) => render.render_number === data.render_number,
  );
  const writing = isJobActive(data?.job);
  const blocked = data?.blocked_reason ?? null;
  const job = data?.job ?? null;
  // The story render that is waiting or running: its draft and thumbnails are already being
  // made, and the panel shows them while Upload waits for the video.
  const rendering = data?.rendering ?? null;
  const showingRendering = data?.render_number === null && rendering !== null;
  const hasSomethingToPublish =
    data !== undefined && (data.renders.length > 0 || rendering !== null);

  // A new version of the draft starts again at the defaults.
  const current: Answers =
    draft !== null && answers.version === draft.version
      ? answers
      : DEFAULT_ANSWERS;
  const answer = (patch: Partial<Answers>) =>
    setAnswers({
      ...current,
      version: draft?.version ?? null,
      ...patch,
    });

  const startDraft = () => {
    if (data === undefined) {
      return;
    }
    const trimmed = note.trim();
    draftRun.mutate(
      {
        renderNumber: data.render_number,
        feedback: trimmed === "" ? null : trimmed,
      },
      { onSuccess: () => setNote("") },
    );
  };
  const pressDraft = () => {
    if (draft?.source === "manual") {
      setConfirmOwn(true);
    } else {
      startDraft();
    }
  };

  const channels = data?.channels ?? [];
  const connected = channels.filter(
    (channel) => channel.status === "connected",
  );
  const defaultChannel =
    data?.default_channel_row_id != null
      ? String(data.default_channel_row_id)
      : null;
  const channelValue =
    channelChoice !== null &&
    connected.some((channel) => String(channel.id) === channelChoice)
      ? channelChoice
      : defaultChannel;
  const privacy = privacyChoice ?? data?.default_privacy ?? "private";

  // Captions: off without a caption track; otherwise on unless the track is drawn on the picture
  // (viewers with captions on would see them twice), until the owner chooses.
  const hasCaptions = selected?.has_captions ?? false;
  const captionsDefault = hasCaptions && !(selected?.captions_burned ?? false);
  const captions =
    hasCaptions &&
    (captionsChoice !== null &&
    captionsChoice.renderNumber === data?.render_number
      ? captionsChoice.value
      : captionsDefault);

  const channelTitle =
    connected.find((channel) => String(channel.id) === channelValue)?.title ??
    null;
  // The pictures of the newest thumbnail ideas that are still being made. The server checks the
  // same thing when Upload is pressed.
  const newestIdeas = thumbnails.data?.ideas.latest?.version ?? null;
  const picturesMaking =
    newestIdeas !== null &&
    (thumbnails.data?.thumbnails ?? []).some(
      (picture) =>
        picture.concept_version === newestIdeas && isJobActive(picture.job),
    );
  const uploadBlockers = data
    ? whyNotUpload({
        data,
        draft,
        dirty,
        writing,
        picturesMaking,
        channelValue,
        rendering: rendering !== null,
      })
    : ["Loading."];

  const pressUpload = () => {
    if (
      data?.render_number == null ||
      draft === null ||
      channelValue === null
    ) {
      return;
    }
    upload.mutate({
      renderNumber: data.render_number,
      channelRowId: Number(channelValue),
      draftVersion: draft.version,
      privacy,
      madeForKids: current.kids === "yes",
      syntheticMedia: current.synthetic === "yes",
      notifySubscribers: notify,
      captions,
    });
  };

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Stack gap={2}>
            <Title order={4}>Publish to YouTube</Title>
            <Text size="sm" c="dimmed">
              The app drafts the title, description, hashtags, tags and four
              thumbnails for a render, starting when Render is pressed. You
              check and edit everything, check the two questions YouTube asks,
              and choose the channel. Nothing is uploaded unless you press
              Upload, which waits for the video to be finished.
            </Text>
          </Stack>
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the YouTube draft">
              {describeError(error)}
            </Alert>
          )}
          {blocked !== null && (
            <Text size="sm" c="dimmed">
              {blocked}
            </Text>
          )}
          {data && hasSomethingToPublish && (
            <Select
              label="Render to publish"
              allowDeselect={false}
              data={[
                ...(rendering !== null
                  ? [{ value: RENDERING_VALUE, label: "Render being made now" }]
                  : []),
                ...data.renders.map((render) => ({
                  value: String(render.render_number),
                  label: [
                    `Render ${render.render_number}`,
                    render.is_short ? "a Short" : null,
                    render.status === "out_of_date" ? "out of date" : null,
                  ]
                    .filter((part) => part !== null)
                    .join(", "),
                })),
              ]}
              value={
                showingRendering
                  ? RENDERING_VALUE
                  : data.render_number === null
                    ? null
                    : String(data.render_number)
              }
              onChange={(value) => {
                if (value === RENDERING_VALUE) {
                  // Back to the default, which is the render being made.
                  setRenderNumber(null);
                } else if (value) {
                  setRenderNumber(Number(value));
                }
              }}
            />
          )}
          {showingRendering && rendering !== null && (
            <Text size="xs" c="dimmed">
              The video is still rendering
              {rendering.phase ? ` (${rendering.phase})` : ""}. Its draft and
              thumbnails are being made now, and Upload waits for the video.
            </Text>
          )}
          {selected?.is_short && (
            <Text size="xs" c="dimmed">
              It is vertical and at most three minutes, so YouTube will show it
              as a Short.
            </Text>
          )}
          {selected?.status === "out_of_date" && (
            <Alert color="yellow" title="This render is out of date">
              <Stack gap={4}>
                <Text size="sm">
                  The story has changed since it was rendered. You can still
                  publish it.
                </Text>
                <List size="sm">
                  {selected.reasons.map((reason) => (
                    <List.Item key={reason}>{reason}</List.Item>
                  ))}
                </List>
              </Stack>
            </Alert>
          )}
          {data && data.render_number !== null && (
            <PublishedBefore data={data} renderNumber={data.render_number} />
          )}
        </Stack>
      </Paper>

      {data && hasSomethingToPublish && (
        <Paper withBorder p="md" radius="md">
          <Stack gap="sm">
            <Group gap="xs">
              <Title order={5}>Draft</Title>
              {draft && (
                <Badge
                  variant="light"
                  color={draft.source === "manual" ? "blue" : "gray"}
                >
                  Version {draft.version},{" "}
                  {draft.source === "manual"
                    ? "written by you"
                    : "written by the model"}
                </Badge>
              )}
            </Group>
            {draft && draftOrigin(draft) !== null && (
              <Text size="sm" c="dimmed">
                {draftOrigin(draft)}
              </Text>
            )}
            {draft?.feedback && (
              <Text size="sm" c="dimmed">
                Your note: {draft.feedback}
              </Text>
            )}
            {draft && (
              <Textarea
                label="A note for the model (optional)"
                description="For example: shorter title, more about the ending, no spoilers."
                autosize
                minRows={1}
                maxRows={4}
                value={note}
                onChange={(event) => setNote(event.currentTarget.value)}
              />
            )}
            <Group>
              <Button
                onClick={pressDraft}
                loading={draftRun.isPending || writing}
                disabled={isLoading || isError || blocked !== null}
              >
                {draft ? "Draft again" : "Draft for YouTube"}
              </Button>
            </Group>
            {draftRun.isError && (
              <Alert color="red" title="Could not start the draft">
                {describeError(draftRun.error)}
              </Alert>
            )}
            {draftRun.data?.thumbnail_note != null && (
              <Alert color="yellow" title="The thumbnail was not started">
                {draftRun.data.thumbnail_note}
              </Alert>
            )}
            {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
            {job?.status === "failed" && !writing && (
              <Alert color="red" title="The last draft failed">
                {job.error ?? "The job failed."}
              </Alert>
            )}
            {draft?.out_of_date && (
              <Alert color="yellow" title="The draft is out of date">
                <Stack gap={4}>
                  <Text size="sm">
                    Something it was written from has changed. You can still use
                    it, or draft again.
                  </Text>
                  <List size="sm">
                    {draft.reasons.map((reason) => (
                      <List.Item key={reason}>{reason}</List.Item>
                    ))}
                  </List>
                </Stack>
              </Alert>
            )}
            {draft && (
              <YouTubeDraftEditor
                key={draft.version}
                draft={draft}
                busy={writing}
                saving={save.isPending}
                saveError={save.error}
                onSave={(edit) =>
                  save.mutate({ renderNumber: data.render_number, ...edit })
                }
                onDirtyChange={onDirtyChange}
              />
            )}
          </Stack>
        </Paper>
      )}

      {data && hasSomethingToPublish && (
        <YouTubeThumbnailsSection
          projectId={projectId}
          thumbnail={data.thumbnail}
        />
      )}

      {data && draft && (
        <Paper withBorder p="md" radius="md">
          <Stack gap="md">
            <Title order={5}>Before uploading</Title>
            <Declaration
              label="Made for kids"
              question="Is this video made for children as its main audience? (YouTube asks this for every video.)"
              value={current.kids}
              onChange={(value) => answer({ kids: value })}
            />
            <Declaration
              label="Contains realistic AI content"
              question="Does it show realistic people, places, events or voices that were made or changed by AI, so that a viewer could take them for real?"
              value={current.synthetic}
              onChange={(value) => answer({ synthetic: value })}
            />
            {connected.length === 0 && channels.length === 0 ? (
              <Text size="sm" c="dimmed">
                No YouTube channel is connected. Connect one on the{" "}
                <Anchor component={Link} to="/settings" size="sm">
                  Settings
                </Anchor>{" "}
                page, in the YouTube tab.
              </Text>
            ) : (
              <Select
                label="Channel"
                allowDeselect={false}
                data={channels.map((channel) => ({
                  value: String(channel.id),
                  label:
                    channel.status === "connected"
                      ? channel.title
                      : `${channel.title} (reconnect it in Settings)`,
                  disabled: channel.status !== "connected",
                }))}
                value={channelValue}
                onChange={setChannelChoice}
              />
            )}
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                Visibility
              </Text>
              <SegmentedControl
                data={PRIVACY_OPTIONS}
                value={privacy}
                onChange={(value) => setPrivacyChoice(value as YouTubePrivacy)}
              />
            </Stack>
            <Checkbox
              label="Notify subscribers"
              description="YouTube tells the channel's subscribers about the new video. It has no effect on a private video."
              checked={notify}
              onChange={(event) => setNotify(event.currentTarget.checked)}
            />
            <Checkbox
              label="Upload captions"
              description={
                !hasCaptions
                  ? "This render has no caption track, so there is nothing to upload."
                  : selected?.captions_burned
                    ? "The captions are already drawn on the picture. Uploading them too would show them twice to viewers who turn captions on."
                    : "Sends the render's words and timing to YouTube as an English caption track (SRT)."
              }
              checked={captions}
              disabled={!hasCaptions}
              onChange={(event) =>
                data?.render_number != null &&
                setCaptionsChoice({
                  renderNumber: data.render_number,
                  value: event.currentTarget.checked,
                })
              }
            />
            <Stack gap={4}>
              <Group>
                <Button
                  disabled={uploadBlockers.length > 0}
                  loading={upload.isPending}
                  onClick={() => setConfirmUpload(true)}
                >
                  Upload
                </Button>
              </Group>
              {uploadBlockers.map((reason) => (
                <Text key={reason} size="xs" c="dimmed">
                  {reason}
                </Text>
              ))}
            </Stack>
            {upload.isError && (
              <Alert color="red" title="The upload was not started">
                {describeError(upload.error)}
              </Alert>
            )}
          </Stack>
        </Paper>
      )}

      {data && data.uploads.length > 0 && (
        <UploadsCard
          uploads={data.uploads}
          retrying={retry.isPending ? retry.variables : null}
          retryError={retry.isError ? describeError(retry.error) : null}
          onRetry={(request) => retry.mutate(request)}
          sending={send.isPending ? send.variables : null}
          sendError={send.isError ? describeError(send.error) : null}
          onSend={(request) => send.mutate(request)}
        />
      )}

      <Modal
        opened={confirmUpload}
        onClose={() => setConfirmUpload(false)}
        title="Upload to YouTube?"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Render {data?.render_number} will be sent to{" "}
            <strong>{channelTitle ?? "the chosen channel"}</strong> now, as{" "}
            <strong>{privacy}</strong>.{" "}
            {notify
              ? "YouTube will notify the channel's subscribers."
              : "Subscribers will not be notified."}{" "}
            {captions
              ? "The captions will be uploaded too."
              : "No captions will be uploaded."}
          </Text>
          <Text size="sm">
            Made for kids:{" "}
            <strong>{current.kids === "yes" ? "Yes" : "No"}</strong>. Contains
            realistic AI content:{" "}
            <strong>{current.synthetic === "yes" ? "Yes" : "No"}</strong>.
          </Text>
          <Text size="sm" c="dimmed">
            These two answers are sent with the video, and YouTube may act on
            them. You can follow the upload below.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmUpload(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                setConfirmUpload(false);
                pressUpload();
              }}
            >
              Upload
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={confirmOwn}
        onClose={() => setConfirmOwn(false)}
        title="Draft again?"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            The newest version is the one you wrote. The model will write a new
            version from the story, with your note if you gave one. Your version
            stays in the history.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmOwn(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                setConfirmOwn(false);
                startDraft();
              }}
            >
              Draft again
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

/**
 * Everything that stops Upload, one sentence each, or an empty list when nothing in this panel
 * does. The server checks the same things again when Upload is pressed.
 */
function whyNotUpload(input: {
  data: YouTubePanel;
  draft: YouTubeDraft | null;
  dirty: boolean;
  writing: boolean;
  picturesMaking: boolean;
  channelValue: string | null;
  rendering: boolean;
}): string[] {
  const {
    data,
    draft,
    dirty,
    writing,
    picturesMaking,
    channelValue,
    rendering,
  } = input;
  const reasons: string[] = [];
  if (rendering) {
    reasons.push("The video is still rendering.");
  }
  if (writing) {
    reasons.push("The draft is still being written.");
  } else if (draft === null) {
    reasons.push("Write the draft first.");
  }
  if (dirty) {
    reasons.push("Save your edits first.");
  }
  if (data.thumbnail.status === "making" || picturesMaking) {
    reasons.push("The thumbnails are still being made.");
  } else if (data.thumbnail.thumbnail_id === null) {
    reasons.push("There is no chosen thumbnail yet.");
  }
  if (channelValue === null) {
    reasons.push("Choose a connected channel.");
  } else if (
    data.uploads.some(
      (upload) =>
        upload.render_number === data.render_number &&
        upload.channel_row_id === Number(channelValue) &&
        isUploadActive(upload),
    )
  ) {
    reasons.push("This render is already being uploaded to that channel.");
  }
  return reasons;
}

/**
 * Where a draft that was written with its render started (YTF-004) says it came from, or null
 * when there is nothing to say.
 */
function draftOrigin(draft: YouTubeDraft): string | null {
  if (draft.render_state === "not_made") {
    return "Drafted for a render that was not made.";
  }
  if (!draft.started_at_render) {
    return null;
  }
  if (draft.render_state === "rendering") {
    return "Drafted when this render was started.";
  }
  if (draft.render_state === "made" && draft.render_number !== null) {
    return `Drafted when render ${draft.render_number} was started.`;
  }
  return null;
}

function isUploadActive(upload: YouTubeUpload): boolean {
  return (
    upload.state === "uploading" ||
    upload.state === "processing" ||
    upload.state === "finishing"
  );
}

const UPLOAD_STATE: Record<
  YouTubeUpload["state"],
  { label: string; color: string }
> = {
  uploading: { label: "Sending", color: "blue" },
  processing: { label: "YouTube is processing it", color: "blue" },
  finishing: { label: "Setting thumbnail and captions", color: "blue" },
  processed: { label: "Uploaded", color: "green" },
  gave_up: { label: "Uploaded, still processing", color: "yellow" },
  failed: { label: "Failed", color: "red" },
};

/** Every upload of the project, newest first, with its progress, links and result. */
function UploadsCard({
  uploads,
  retrying,
  retryError,
  onRetry,
  sending,
  sendError,
  onSend,
}: {
  uploads: YouTubeUpload[];
  retrying: YouTubeRetryRequest | null | undefined;
  retryError: string | null;
  onRetry: (request: YouTubeRetryRequest) => void;
  // The send-later request now being sent, or null.
  sending: YouTubeSendRequest | null | undefined;
  sendError: string | null;
  onSend: (request: YouTubeSendRequest) => void;
}) {
  // The send-later action waiting for the owner's confirmation.
  const [toConfirm, setToConfirm] = useState<YouTubeSendRequest | null>(null);
  const confirming =
    toConfirm !== null
      ? (uploads.find((upload) => upload.id === toConfirm.uploadId) ?? null)
      : null;
  const channelName = confirming?.channel_title ?? "the channel";
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="md">
        <Title order={5}>Uploads</Title>
        {retryError !== null && (
          <Alert color="red" title="Could not try again">
            {retryError}
          </Alert>
        )}
        {sendError !== null && (
          <Alert color="red" title="Could not send it">
            {sendError}
          </Alert>
        )}
        {uploads.map((upload) => (
          <UploadRow
            key={upload.id}
            upload={upload}
            retrying={retrying?.uploadId === upload.id ? retrying : null}
            onRetry={(step) => onRetry({ uploadId: upload.id, step })}
            sendingStep={sending?.uploadId === upload.id ? sending.step : null}
            onSend={(step) => setToConfirm({ uploadId: upload.id, step })}
          />
        ))}
      </Stack>
      <Modal
        opened={confirming !== null && toConfirm !== null}
        onClose={() => setToConfirm(null)}
        title={
          toConfirm?.step === "captions"
            ? "Send the captions now?"
            : "Set the thumbnail again?"
        }
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            {toConfirm?.step === "captions"
              ? `The captions of render ${confirming?.render_number} will be uploaded to this video on ${channelName} as an English track.`
              : `The thumbnail chosen for this project now will be set on this video on ${channelName}.`}{" "}
            Nothing else about the video is changed.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setToConfirm(null)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (toConfirm !== null) {
                  onSend(toConfirm);
                }
                setToConfirm(null);
              }}
            >
              {toConfirm?.step === "captions"
                ? "Send captions"
                : "Set thumbnail"}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
}

function UploadRow({
  upload,
  retrying,
  onRetry,
  sendingStep,
  onSend,
}: {
  upload: YouTubeUpload;
  // The retry now being sent for this upload, or null.
  retrying: YouTubeRetryRequest | null;
  onRetry: (step?: "thumbnail" | "captions") => void;
  // The step whose send-later request is being sent now, or null.
  sendingStep: "thumbnail" | "captions" | null;
  onSend: (step: "thumbnail" | "captions") => void;
}) {
  const state = UPLOAD_STATE[upload.state];
  const finishing = upload.state === "finishing";
  // Offered on a processed upload; the captions one is left out while their own Try again is
  // shown, because both would do the same.
  const canSendThumbnail = upload.send_steps.includes("thumbnail");
  const canSendCaptions =
    upload.send_steps.includes("captions") &&
    !upload.retry_steps.includes("captions");
  const progress = upload.progress;
  const percent =
    progress !== null && progress.total_bytes > 0
      ? Math.min(100, (progress.sent_bytes / progress.total_bytes) * 100)
      : 0;
  const privacyDiffers =
    upload.privacy_applied !== null &&
    upload.privacy_sent !== null &&
    upload.privacy_applied !== upload.privacy_sent;
  return (
    <Stack gap={4}>
      <Group gap="xs">
        <Text size="sm" fw={500}>
          Render {upload.render_number},{" "}
          {upload.channel_title ?? "a channel that was disconnected"}
        </Text>
        <Badge variant="light" color={state.color}>
          {state.label}
        </Badge>
      </Group>
      <Text size="xs" c="dimmed">
        {upload.title ? `"${upload.title}", ` : ""}
        {formatDateTime(upload.created_at)}
        {upload.privacy_sent ? `, asked for ${upload.privacy_sent}` : ""}
      </Text>
      {upload.state === "uploading" && (
        <Stack gap={2}>
          <Progress value={percent} size="sm" />
          <Text size="xs" c="dimmed">
            {progress !== null
              ? `${formatBytes(progress.sent_bytes)} of ${formatBytes(progress.total_bytes)} (${Math.round(percent)}%)`
              : (upload.job?.phase ?? "Waiting to start.")}
          </Text>
        </Stack>
      )}
      {upload.state === "processing" && (
        <Text size="xs" c="dimmed">
          The video is on YouTube. YouTube is processing it; this page updates
          by itself.
        </Text>
      )}
      {upload.state === "gave_up" && (
        <Text size="xs" c="dimmed">
          YouTube was still processing the video after 30 minutes, so the app
          stopped waiting. The video is on YouTube, but its thumbnail and
          captions have not been sent yet.
        </Text>
      )}
      {(finishing ||
        upload.state === "processed" ||
        upload.thumbnail_result !== null ||
        upload.captions_result !== null) && (
        <Stack gap={2}>
          <StepLine
            label="Thumbnail"
            doneText="Set on the video."
            result={upload.thumbnail_result}
            working={finishing && upload.sending_steps.includes("thumbnail")}
            canRetry={upload.retry_steps.includes("thumbnail")}
            retrying={retrying?.step === "thumbnail"}
            onRetry={() => onRetry("thumbnail")}
            sendLabel={canSendThumbnail ? "Set the thumbnail again" : null}
            sending={sendingStep === "thumbnail"}
            onSend={() => onSend("thumbnail")}
          />
          {upload.thumbnail_result?.status === "done" &&
            upload.thumbnail_result.from_snapshot === false &&
            !upload.thumbnail_result.later && (
              <Text size="xs" c="dimmed">
                The picture recorded when you pressed Upload had changed, so the
                thumbnail chosen now was set instead.
              </Text>
            )}
          <StepLine
            label="Captions"
            doneText="Uploaded as an English track."
            result={upload.captions_result}
            working={finishing && upload.sending_steps.includes("captions")}
            canRetry={upload.retry_steps.includes("captions")}
            retrying={retrying?.step === "captions"}
            onRetry={() => onRetry("captions")}
            sendLabel={canSendCaptions ? "Send captions now" : null}
            sending={sendingStep === "captions"}
            onSend={() => onSend("captions")}
          />
        </Stack>
      )}
      {upload.can_finish && (
        <Group>
          <Button
            size="xs"
            variant="light"
            onClick={() => onRetry()}
            loading={retrying !== null && retrying.step === undefined}
          >
            Finish the thumbnail and captions
          </Button>
        </Group>
      )}
      {upload.video_id && (
        <Group gap="md">
          <Anchor
            href={`https://youtu.be/${upload.video_id}`}
            target="_blank"
            rel="noreferrer"
            size="xs"
          >
            Open on YouTube
          </Anchor>
          <Anchor
            href={`https://studio.youtube.com/video/${upload.video_id}/edit`}
            target="_blank"
            rel="noreferrer"
            size="xs"
          >
            Open in YouTube Studio
          </Anchor>
        </Group>
      )}
      {privacyDiffers && (
        <Alert color="yellow" title="YouTube used another visibility">
          <Text size="sm">
            You asked for {upload.privacy_sent}, but YouTube made the video{" "}
            {upload.privacy_applied}. Check it in YouTube Studio.
          </Text>
        </Alert>
      )}
      {upload.state === "failed" && (
        <Alert color="red" title="The upload failed">
          <Stack gap="xs">
            <Text size="sm">{upload.error ?? "The job failed."}</Text>
            {upload.video_id && (
              <Text size="xs" c="dimmed">
                The video is already on YouTube; trying again will not send it
                twice.
              </Text>
            )}
            {upload.can_retry && (
              <Group>
                <Button
                  size="xs"
                  onClick={() => onRetry()}
                  loading={retrying !== null && retrying.step === undefined}
                >
                  Try again
                </Button>
              </Group>
            )}
          </Stack>
        </Alert>
      )}
    </Stack>
  );
}

/** One line for the thumbnail or the captions step of an upload. */
function StepLine({
  label,
  doneText,
  result,
  working,
  canRetry,
  retrying,
  onRetry,
  sendLabel,
  sending,
  onSend,
}: {
  label: string;
  doneText: string;
  result: YouTubeUpload["thumbnail_result"];
  // The job is sending this step now (an earlier failure is being tried again, or it is being
  // sent again).
  working: boolean;
  canRetry: boolean;
  retrying: boolean;
  onRetry: () => void;
  // The text of the send-later button, or null when it is not offered.
  sendLabel: string | null;
  sending: boolean;
  onSend: () => void;
}) {
  let text: string;
  let color = "dimmed";
  if (working) {
    if (result === null) {
      text = "Being sent.";
    } else {
      text = result.status === "failed" ? "Trying again." : "Sending again.";
    }
  } else if (result === null) {
    text = "Not sent yet.";
  } else if (result.status === "done") {
    text = result.message ?? doneText;
  } else if (result.status === "skipped") {
    text = result.message ?? "Not sent.";
  } else {
    text = result.message ?? "It failed.";
    color = "red";
  }
  return (
    <Group gap="xs">
      <Text size="xs" fw={500}>
        {label}:
      </Text>
      <Text size="xs" c={color}>
        {text}
      </Text>
      {!working && result?.later && result.at && (
        <Text size="xs" c="dimmed">
          Sent later, {formatDateTime(result.at)}.
        </Text>
      )}
      {canRetry && (
        <Button size="compact-xs" onClick={onRetry} loading={retrying}>
          Try again
        </Button>
      )}
      {sendLabel !== null && (
        <Button
          size="compact-xs"
          variant="light"
          onClick={onSend}
          loading={sending}
        >
          {sendLabel}
        </Button>
      )}
    </Group>
  );
}

function PublishedBefore({
  data,
  renderNumber,
}: {
  data: YouTubePanel;
  renderNumber: number;
}) {
  const earlier = data.uploads.filter(
    (upload) => upload.render_number === renderNumber,
  );
  if (earlier.length === 0) {
    return null;
  }
  return (
    <Stack gap={2}>
      <Text size="sm" fw={500}>
        Already uploaded
      </Text>
      {earlier.map((upload) => (
        <Text key={upload.id} size="xs" c="dimmed">
          {upload.channel_title ?? "A channel that was disconnected"},{" "}
          {formatDateTime(upload.created_at)}
          {upload.privacy_applied ? `, ${upload.privacy_applied}` : ""}
          {upload.video_id && (
            <>
              {", "}
              <Anchor
                href={`https://youtu.be/${upload.video_id}`}
                target="_blank"
                rel="noreferrer"
                size="xs"
              >
                open on YouTube
              </Anchor>
            </>
          )}
        </Text>
      ))}
    </Stack>
  );
}

function Declaration({
  label,
  question,
  value,
  onChange,
}: {
  label: string;
  question: string;
  value: Answer;
  onChange: (value: Answer) => void;
}) {
  return (
    <Stack gap={4}>
      <Radio.Group
        label={label}
        description={question}
        value={value}
        onChange={(next) => onChange(next as Answer)}
      >
        <Group mt="xs">
          <Radio value="yes" label="Yes" />
          <Radio value="no" label="No" />
        </Group>
      </Radio.Group>
    </Stack>
  );
}
