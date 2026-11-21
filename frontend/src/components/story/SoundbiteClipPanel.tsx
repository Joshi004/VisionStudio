import { Alert, Badge, Button, Group, Loader, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useTranscribeEvidenceClip, type EvidenceReviewItem } from "../../api/evidence";

const FIDELITY_LABEL: Record<string, string> = {
  exact: "Exact words",
  near: "Nearly the same words",
  paraphrase: "Paraphrase",
  mismatch: "Not the quote",
};

const FIDELITY_COLOR: Record<string, string> = {
  exact: "green",
  near: "teal",
  paraphrase: "orange",
  mismatch: "red",
};

const LICENCE_LABEL: Record<string, string> = {
  standard: "Standard licence",
  creative_commons: "Creative Commons",
  unknown: "Licence unknown",
};

function seconds(value: number): string {
  return `${value.toFixed(2)} s`;
}

/**
 * A sound bite clip as it was imported (SB-006): the video, what the app heard in it, how close
 * that is to the claim's words, the proposed cut and the things to check. Read-only: the owner
 * decides on clips in the sound bite review that comes next.
 */
export function SoundbiteClipPanel({
  item,
  projectId,
  disabled,
}: {
  item: EvidenceReviewItem;
  projectId: number;
  disabled: boolean;
}) {
  const retry = useTranscribeEvidenceClip(projectId);
  const clip = item.soundbite;
  if (clip === null || !item.usable) {
    return null;
  }
  const status = clip.transcription.status;
  const heard = clip.heard;
  const trim = clip.proposed_trim;
  const match = heard?.match ?? null;

  return (
    <Stack gap="xs">
      {clip.video_url !== null && (
        <video
          src={clip.video_url}
          controls
          preload="metadata"
          style={{ maxWidth: "100%", maxHeight: 320 }}
        />
      )}

      <Group gap="xs">
        <Badge size="sm" variant="light" color="gray">
          Sound bite clip
        </Badge>
        {clip.licence !== null && (
          <Badge
            size="sm"
            variant="outline"
            color={clip.licence === "unknown" ? "orange" : "gray"}
          >
            {LICENCE_LABEL[clip.licence] ?? clip.licence}
          </Badge>
        )}
        {clip.fidelity !== null && (
          <Badge size="sm" variant="filled" color={FIDELITY_COLOR[clip.fidelity] ?? "gray"}>
            {FIDELITY_LABEL[clip.fidelity] ?? clip.fidelity}
            {match !== null ? `, ${Math.round(match.percent)}%` : ""}
          </Badge>
        )}
      </Group>

      <Text size="xs" c="dimmed">
        {[
          clip.channel,
          clip.upload_date,
          clip.window !== null
            ? `video ${seconds(clip.window.start_s)} to ${seconds(clip.window.end_s)}`
            : null,
        ]
          .filter((part) => part !== null && part !== "")
          .join(", ")}
      </Text>

      {status === "in_progress" && (
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="xs">Listening to the clip...</Text>
        </Group>
      )}

      {status === "failed" && (
        <Alert color="red" p="xs" title="Transcription failed">
          <Stack gap={4}>
            <Text size="xs">{clip.transcription.error ?? "The clip could not be transcribed."}</Text>
            <Group>
              <Button
                size="compact-xs"
                variant="light"
                loading={retry.isPending}
                disabled={disabled}
                onClick={() => retry.mutate(item.item_key)}
              >
                Transcribe again
              </Button>
            </Group>
            {retry.isError && (
              <Text size="xs" c="red">
                {describeError(retry.error)}
              </Text>
            )}
          </Stack>
        </Alert>
      )}

      {heard !== null && (
        <Stack gap={2}>
          <Text size="xs" fw={600}>
            What the app heard
          </Text>
          <Text size="sm">{heard.text !== "" ? heard.text : "No words were heard."}</Text>
        </Stack>
      )}

      {match !== null && match.diff.length > 0 && (
        <Stack gap={2}>
          <Text size="xs" fw={600}>
            Differences from the claim&apos;s words
          </Text>
          {match.diff.map((entry, index) => (
            <Text key={index} size="xs" c="dimmed">
              {entry.op === "insert" && `Added in the clip: "${entry.heard}"`}
              {entry.op === "delete" && `Missing from the clip: "${entry.script}"`}
              {entry.op === "replace" && `"${entry.script}" is heard as "${entry.heard}"`}
            </Text>
          ))}
        </Stack>
      )}

      {trim !== null && (
        <Text size="xs" c="dimmed">
          Proposed cut: {seconds(trim.in_s)} to {seconds(trim.out_s)} of the clip
          {trim.in_clean && trim.out_clean ? "" : " (an edge is not in a quiet gap)"}
        </Text>
      )}

      {clip.flags.map((flag) => (
        <Text key={flag.code} size="xs" c="orange">
          {flag.message}
        </Text>
      ))}

      <Text size="xs" c="dimmed">
        Clips are accepted or rejected in the sound bite review, which comes next.
      </Text>
    </Stack>
  );
}
