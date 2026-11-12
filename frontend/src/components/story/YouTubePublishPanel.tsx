import { useCallback, useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Group,
  Image,
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
import {
  useDraftForYouTube,
  useRetryYouTubeUpload,
  useSaveYouTubeDraft,
  useUploadToYouTube,
  useYouTubePanel,
  type YouTubeDraft,
  type YouTubePanel,
  type YouTubePrivacy,
  type YouTubeThumbnail,
  type YouTubeUpload,
} from "../../api/youtube";
import { formatBytes, formatDateTime } from "../../format";
import { stepPath } from "../board/boardSteps";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { YouTubeDraftEditor } from "./YouTubeDraftEditor";

type YouTubePublishPanelProps = {
  projectId: number;
};

const PRIVACY_OPTIONS: { value: YouTubePrivacy; label: string }[] = [
  { value: "private", label: "Private" },
  { value: "unlisted", label: "Unlisted" },
  { value: "public", label: "Public" },
];

const THUMBNAIL_STATUS: Record<
  YouTubeThumbnail["status"],
  { label: string; color: string }
> = {
  ready: { label: "Ready", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
  making: { label: "Being made", color: "blue" },
  none: { label: "None yet", color: "gray" },
};

type Answer = "yes" | "no" | "";

/** The owner's answers to the two declarations, for one version of the draft. */
type Answers = { version: number | null; kids: Answer; synthetic: Answer };

const NO_ANSWERS: Answers = { version: null, kids: "", synthetic: "" };

/**
 * Publishing a finished render to YouTube. The app writes a draft (title, description, hashtags,
 * a suggestion for the two declarations) and a thumbnail; the owner edits everything, picks the
 * channel and visibility, and answers both declarations. Upload is disabled with its reason
 * until all of that is done, asks for a confirmation, and sends the render; the Uploads card
 * follows each upload. The thumbnail and the captions are sent in the next update.
 */
export function YouTubePublishPanel({ projectId }: YouTubePublishPanelProps) {
  const [renderNumber, setRenderNumber] = useState<number | null>(null);
  const { data, isLoading, isError, error } = useYouTubePanel(
    projectId,
    renderNumber,
  );
  const draftRun = useDraftForYouTube(projectId);
  const save = useSaveYouTubeDraft(projectId);
  const [note, setNote] = useState("");
  const upload = useUploadToYouTube(projectId);
  const retry = useRetryYouTubeUpload(projectId);
  const [confirmOwn, setConfirmOwn] = useState(false);
  const [confirmUpload, setConfirmUpload] = useState(false);
  const [notify, setNotify] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [answers, setAnswers] = useState<Answers>(NO_ANSWERS);
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

  // Nothing is preselected, and a new version of the draft starts with nothing answered.
  const current: Answers =
    draft !== null && answers.version === draft.version ? answers : NO_ANSWERS;
  const answer = (patch: Partial<Answers>) =>
    setAnswers({
      ...current,
      version: draft?.version ?? null,
      ...patch,
    });

  const startDraft = () => {
    if (data?.render_number == null) {
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
  const connected = channels.filter((channel) => channel.status === "connected");
  const defaultChannel =
    data?.default_channel_row_id != null ? String(data.default_channel_row_id) : null;
  const channelValue =
    channelChoice !== null &&
    connected.some((channel) => String(channel.id) === channelChoice)
      ? channelChoice
      : defaultChannel;
  const privacy = privacyChoice ?? data?.default_privacy ?? "private";

  const channelTitle =
    connected.find((channel) => String(channel.id) === channelValue)?.title ??
    null;
  const uploadBlocker = data
    ? whyNotUpload({
        data,
        draft,
        dirty,
        writing,
        answers: current,
        channelValue,
      })
    : "Loading.";

  const pressUpload = () => {
    if (
      data?.render_number == null ||
      draft === null ||
      channelValue === null ||
      current.kids === "" ||
      current.synthetic === ""
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
      // The captions come in the next update.
      captions: false,
    });
  };

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Stack gap={2}>
            <Title order={4}>Publish to YouTube</Title>
            <Text size="sm" c="dimmed">
              Pick a finished render and the app drafts its title, description,
              hashtags and thumbnail. You check and edit everything, answer two
              questions YouTube asks, and choose the channel. Nothing is
              uploaded unless you press Upload.
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
          {data && data.renders.length > 0 && (
            <Select
              label="Render to publish"
              allowDeselect={false}
              data={data.renders.map((render) => ({
                value: String(render.render_number),
                label: [
                  `Render ${render.render_number}`,
                  render.is_short ? "a Short" : null,
                  render.status === "out_of_date" ? "out of date" : null,
                ]
                  .filter((part) => part !== null)
                  .join(", "),
              }))}
              value={data.render_number === null ? null : String(data.render_number)}
              onChange={(value) => value && setRenderNumber(Number(value))}
            />
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

      {data && data.renders.length > 0 && (
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
                    Something it was written from has changed. You can still
                    use it, or draft again.
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
                onSave={(edit) => {
                  if (data.render_number !== null) {
                    save.mutate({ renderNumber: data.render_number, ...edit });
                  }
                }}
                onDirtyChange={onDirtyChange}
              />
            )}
          </Stack>
        </Paper>
      )}

      {data && draft && (
        <ThumbnailCard projectId={projectId} thumbnail={data.thumbnail} />
      )}

      {data && draft && (
        <Paper withBorder p="md" radius="md">
          <Stack gap="md">
            <Title order={5}>Before uploading</Title>
            <Declaration
              label="Made for kids"
              question="Is this video made for children as its main audience? (YouTube asks this for every video.)"
              suggestion={draft.made_for_kids}
              value={current.kids}
              onChange={(value) => answer({ kids: value })}
            />
            <Declaration
              label="Contains realistic AI content"
              question="Does it show realistic people, places, events or voices that were made or changed by AI, so that a viewer could take them for real?"
              suggestion={draft.synthetic_media}
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
            <Stack gap={4}>
              <Group>
                <Button
                  disabled={uploadBlocker !== null}
                  loading={upload.isPending}
                  onClick={() => setConfirmUpload(true)}
                >
                  Upload
                </Button>
              </Group>
              {uploadBlocker !== null && (
                <Text size="xs" c="dimmed">
                  {uploadBlocker}
                </Text>
              )}
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
          onRetry={(uploadId) => retry.mutate(uploadId)}
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
              : "Subscribers will not be notified."}
          </Text>
          <Text size="sm" c="dimmed">
            Your answers to the two questions are sent with it, and YouTube may
            act on them. You can follow the upload below.
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

/** The first thing that stops Upload, or null when nothing in this panel does. */
function whyNotUpload(input: {
  data: YouTubePanel;
  draft: YouTubeDraft | null;
  dirty: boolean;
  writing: boolean;
  answers: Answers;
  channelValue: string | null;
}): string | null {
  const { data, draft, dirty, writing, answers, channelValue } = input;
  if (draft === null) {
    return "Write the draft first.";
  }
  if (writing) {
    return "The draft is being written.";
  }
  if (dirty) {
    return "Save your edits first.";
  }
  if (data.thumbnail.status === "making") {
    return "The thumbnail is still being made.";
  }
  if (data.thumbnail.thumbnail_id === null) {
    return "There is no chosen thumbnail yet.";
  }
  if (channelValue === null) {
    return "Choose a connected channel.";
  }
  if (
    data.uploads.some(
      (upload) =>
        upload.render_number === data.render_number &&
        upload.channel_row_id === Number(channelValue) &&
        isUploadActive(upload),
    )
  ) {
    return "This render is already being uploaded to that channel.";
  }
  if (answers.kids === "") {
    return 'Answer "Made for kids".';
  }
  if (answers.synthetic === "") {
    return 'Answer "Contains realistic AI content".';
  }
  return null;
}

function isUploadActive(upload: YouTubeUpload): boolean {
  return upload.state === "uploading" || upload.state === "processing";
}

const UPLOAD_STATE: Record<
  YouTubeUpload["state"],
  { label: string; color: string }
> = {
  uploading: { label: "Sending", color: "blue" },
  processing: { label: "YouTube is processing it", color: "blue" },
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
}: {
  uploads: YouTubeUpload[];
  retrying: number | null | undefined;
  retryError: string | null;
  onRetry: (uploadId: number) => void;
}) {
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="md">
        <Title order={5}>Uploads</Title>
        {retryError !== null && (
          <Alert color="red" title="Could not try again">
            {retryError}
          </Alert>
        )}
        {uploads.map((upload) => (
          <UploadRow
            key={upload.id}
            upload={upload}
            retrying={retrying === upload.id}
            onRetry={() => onRetry(upload.id)}
          />
        ))}
      </Stack>
    </Paper>
  );
}

function UploadRow({
  upload,
  retrying,
  onRetry,
}: {
  upload: YouTubeUpload;
  retrying: boolean;
  onRetry: () => void;
}) {
  const state = UPLOAD_STATE[upload.state];
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
          stopped waiting. The video is on YouTube and will finish by itself.
        </Text>
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
                <Button size="xs" onClick={onRetry} loading={retrying}>
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

function ThumbnailCard({
  projectId,
  thumbnail,
}: {
  projectId: number;
  thumbnail: YouTubeThumbnail;
}) {
  const display = THUMBNAIL_STATUS[thumbnail.status];
  const portrait =
    thumbnail.width !== null &&
    thumbnail.height !== null &&
    thumbnail.height > thumbnail.width;
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group gap="xs">
          <Title order={5}>Thumbnail</Title>
          <Badge variant="light" color={display.color}>
            {display.label}
          </Badge>
          {thumbnail.status === "making" && <Loader size="xs" />}
        </Group>
        {thumbnail.url !== null && (
          <Image
            src={thumbnail.url}
            alt={thumbnail.headline ?? "The chosen thumbnail"}
            maw={portrait ? 200 : 360}
            radius="sm"
          />
        )}
        {thumbnail.status === "none" && (
          <Text size="sm" c="dimmed">
            There is no chosen thumbnail. One is made when you draft, from the
            frames of the render. You can also make one in the Thumbnails step.
          </Text>
        )}
        {thumbnail.status === "making" && (
          <Text size="sm" c="dimmed">
            The thumbnail is being made. It is chosen when it is ready, unless
            you choose another one meanwhile.
          </Text>
        )}
        {thumbnail.status === "out_of_date" && (
          <Alert color="yellow" title="The chosen thumbnail is out of date">
            <List size="sm">
              {thumbnail.reasons.map((reason) => (
                <List.Item key={reason}>{reason}</List.Item>
              ))}
            </List>
          </Alert>
        )}
        {thumbnail.error !== null && (
          <Alert color="red" title="The last thumbnail attempt failed">
            {thumbnail.error}
          </Alert>
        )}
        <Group>
          <Button
            component={Link}
            to={stepPath(projectId, "thumbnail")}
            variant="default"
            size="compact-sm"
          >
            Change in Thumbnails
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function Declaration({
  label,
  question,
  suggestion,
  value,
  onChange,
}: {
  label: string;
  question: string;
  suggestion: { value: boolean; reason: string };
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
        withAsterisk
      >
        <Group mt="xs">
          <Radio value="yes" label="Yes" />
          <Radio value="no" label="No" />
        </Group>
      </Radio.Group>
      <Text size="xs" c="dimmed">
        The model suggests {suggestion.value ? "Yes" : "No"}: {suggestion.reason}{" "}
        It is your answer that counts.
      </Text>
    </Stack>
  );
}
