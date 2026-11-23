import { Alert, Badge, Button, Group, Loader, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useTranscribeEvidenceClip, type EvidenceReviewItem } from "../../api/evidence";
import { SoundbitePlayer } from "./SoundbitePlayer";

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

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

// The server checks all of these again; they only keep the Accept button honest.
const MIN_CLIP_S = 3;
const MAX_CLIP_S = 15;
const DATE_PATTERN = /^(\d{4})-(\d{2})-\d{2}$/;

function seconds(value: number): string {
  return `${value.toFixed(2)} s`;
}

/** `2024-03-01` as `March 2024`, or the empty text when it is not a date. */
function monthYear(recorded: string): string {
  const found = DATE_PATTERN.exec(recorded);
  if (found === null) {
    return "";
  }
  const month = Number(found[2]);
  return month >= 1 && month <= 12 ? `${MONTHS[month - 1]} ${Number(found[1])}` : "";
}

/** What the panel needs to know about the claim the clip belongs to. */
export type ClipClaim = {
  // `soundbite` when the owner chose a sound bite for the claim. A video of any other claim is
  // only context: it can be read here but not decided on as a sound bite.
  want: "evidence" | "soundbite";
  speaker: string | null;
};

type Props = {
  item: EvidenceReviewItem;
  projectId: number;
  claim: ClipClaim;
  disabled: boolean;
  onAccept: () => void;
  onReject: () => void;
};

/**
 * A sound bite clip in the review (SB-006, SB-016): the video at the app's cut, what the app
 * heard in it, how close that is to the quote, the cut and the lower third the app made, and
 * Accept or Reject. There is nothing to fill in: the server picks the cut and the details when
 * the clip is accepted. A clip of a claim that is not a sound bite is shown read-only, as context.
 */
export function SoundbiteClipPanel({ item, projectId, claim, disabled, onAccept, onReject }: Props) {
  const retry = useTranscribeEvidenceClip(projectId);
  const clip = item.soundbite;
  const isBite = claim.want === "soundbite";
  const saved = clip?.decision ?? null;
  const heard = clip?.heard ?? null;
  const words = heard?.words ?? [];
  const match = heard?.match ?? null;

  if (clip === null || !item.usable) {
    return null;
  }

  const status = clip.transcription.status;
  const accepted = item.verdict === "accepted";

  // The cut: the one stored with the accepted clip, else the one the app proposed.
  const cut = saved ?? clip.proposed_trim;
  const length = cut !== null ? cut.out_s - cut.in_s : null;
  const first = saved?.first_word ?? match?.first ?? null;
  const last = saved?.last_word ?? match?.last ?? null;

  // The lower third as the accepted clip has it, or as the app will make it.
  const published = item.source?.published ?? "";
  const estimatedDate = DATE_PATTERN.test(published) ? published : (clip.upload_date ?? "");
  const speaker = saved?.speaker ?? claim.speaker ?? "";
  const place = [saved?.role ?? clip.role ?? "", saved?.venue ?? clip.venue ?? ""]
    .filter((part) => part !== "")
    .join(" · ");
  const when = monthYear(saved?.recorded ?? estimatedDate);
  const secondLine = place !== "" && when !== "" ? `${place}, ${when}` : place || when;

  // Why the app cannot make a usable clip. Nothing here is for the owner to fix: reject the clip.
  const blockers: string[] = [];
  if (words.length === 0) {
    blockers.push("the clip has to be heard first");
  }
  if (clip.fidelity !== "exact" && clip.fidelity !== "near") {
    blockers.push("the clip's words are not the quote's words");
  }
  if (cut === null) {
    blockers.push("the app found no cut for this clip");
  } else if (length !== null && (length < MIN_CLIP_S || length > MAX_CLIP_S)) {
    blockers.push(`the cut is ${length.toFixed(1)} s and has to be ${MIN_CLIP_S} to ${MAX_CLIP_S} s`);
  }
  if (speaker.trim() === "") {
    blockers.push("the claim has no speaker name");
  }

  const quoteSpan =
    match !== null && words[match.first] !== undefined && words[match.last] !== undefined
      ? { start: words[match.first].start, end: words[match.last].end }
      : null;
  const cutSpan = isBite && cut !== null ? { start: cut.in_s, end: cut.out_s } : null;
  const otherFlags = clip.flags.filter((flag) => flag.code !== "length");

  return (
    <Stack gap="xs">
      {clip.video_url !== null && (
        <SoundbitePlayer
          src={clip.video_url}
          windowLength={clip.window !== null ? clip.window.end_s - clip.window.start_s : null}
          quote={quoteSpan}
          cut={cutSpan}
        />
      )}

      <Group gap="xs">
        <Badge size="sm" variant="light" color="gray">
          {isBite ? "Sound bite clip" : "Video for context"}
        </Badge>
        {clip.licence !== null && (
          <Badge size="sm" variant="outline" color="gray">
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
          clip.upload_date !== null ? `uploaded ${clip.upload_date}` : null,
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
          {isBite && words.length > 0 ? (
            <Text size="sm" component="div" style={{ lineHeight: 1.9 }}>
              {words.map((word, index) => {
                const inQuote = match !== null && index >= match.first && index <= match.last;
                const inCut = first !== null && last !== null && index >= first && index <= last;
                return (
                  <span
                    key={index}
                    style={{
                      marginRight: 4,
                      padding: "0 2px",
                      borderRadius: 3,
                      background: inQuote ? "var(--mantine-color-yellow-1)" : undefined,
                      textDecoration: inCut ? "underline" : undefined,
                      textDecorationColor: "var(--mantine-color-green-7)",
                      textDecorationThickness: 2,
                      fontWeight: inCut ? 600 : 400,
                      opacity: inCut ? 1 : 0.6,
                    }}
                  >
                    {word.text}
                  </span>
                );
              })}
            </Text>
          ) : (
            <Text size="sm">{heard.text !== "" ? heard.text : "No words were heard."}</Text>
          )}
          {isBite && words.length > 0 && (
            <Text size="xs" c="dimmed">
              Yellow: the words of the quote. Underlined: the words in the cut.
            </Text>
          )}
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

      {cut !== null && (
        <Text size="xs" c="dimmed">
          {isBite ? "The cut" : "Proposed cut"}: {seconds(cut.in_s)} to {seconds(cut.out_s)} of the
          clip{length !== null ? `, ${length.toFixed(1)} s` : ""}
          {cut.in_clean && cut.out_clean ? "" : " (an edge is not in a quiet gap)"}
        </Text>
      )}

      {isBite && (speaker !== "" || secondLine !== "") && (
        <Stack gap={0}>
          <Text size="xs" fw={600}>
            Lower third
          </Text>
          <Text size="sm">{speaker}</Text>
          {secondLine !== "" && (
            <Text size="xs" c="dimmed">
              {secondLine}
            </Text>
          )}
        </Stack>
      )}

      {otherFlags.map((flag) => (
        <Text key={flag.code} size="xs" c="orange">
          {flag.message}
        </Text>
      ))}

      {!isBite && (
        <Text size="xs" c="dimmed">
          This claim is not a sound bite, so the video is context only: it can be accepted for
          the description&apos;s sources, but it is never shown on video.
        </Text>
      )}

      {isBite && (
        <Stack gap={4}>
          <Group gap="sm">
            <Button
              size="xs"
              color="green"
              variant={accepted ? "filled" : "light"}
              disabled={disabled || accepted || blockers.length > 0}
              onClick={onAccept}
            >
              {accepted ? "Accepted" : "Accept"}
            </Button>
            <Button
              size="xs"
              color="gray"
              variant={item.verdict === "rejected" ? "filled" : "light"}
              disabled={disabled}
              onClick={onReject}
            >
              Reject
            </Button>
          </Group>
          {!accepted && blockers.length > 0 && (
            <Text size="xs" c="dimmed">
              This clip cannot be accepted: {blockers.join("; ")}.
            </Text>
          )}
        </Stack>
      )}
    </Stack>
  );
}
