import { useCallback, useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Image,
  List,
  Loader,
  Modal,
  Paper,
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
  useSaveYouTubeDraft,
  useYouTubePanel,
  type YouTubeDraft,
  type YouTubePanel,
  type YouTubePrivacy,
  type YouTubeThumbnail,
} from "../../api/youtube";
import { formatDateTime } from "../../format";
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
 * channel and visibility, and answers both declarations. Upload comes with the next update:
 * the button shows what is still missing, and nothing is sent to YouTube from here.
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
  const [confirmOwn, setConfirmOwn] = useState(false);
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
            <Stack gap={4}>
              <Group>
                <Button disabled>Upload</Button>
              </Group>
              <Text size="xs" c="dimmed">
                {uploadBlocker ?? "Uploading comes in the next update."}
              </Text>
            </Stack>
          </Stack>
        </Paper>
      )}

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
  if (answers.kids === "") {
    return 'Answer "Made for kids".';
  }
  if (answers.synthetic === "") {
    return 'Answer "Contains realistic AI content".';
  }
  return null;
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
