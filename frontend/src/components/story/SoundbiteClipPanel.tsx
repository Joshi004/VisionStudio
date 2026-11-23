import { useState } from "react";

import { Alert, Badge, Button, Group, Loader, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useSoundbiteTrim,
  useTranscribeEvidenceClip,
  type EvidenceReviewItem,
} from "../../api/evidence";
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

// The flags that guard against a quote that changes meaning when it is cut. They are shown in red
// at the top of the card, and Accept asks once more when one is there (SB-017).
const RISKY_FLAG_CODES = [
  "turn_after",
  "reported_speech",
  "hypothetical",
  "admission_words",
  "channel_not_publisher",
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

/** The first and last heard word of a cut, as the server takes them (`CutWordsIn`). */
export type CutWords = { first_word: number; last_word: number };

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
  // `cut` is given only when the owner moved the cut away from the one the app would use.
  onAccept: (cut?: CutWords) => void;
  onReject: () => void;
};

/**
 * A sound bite clip in the review (SB-006, SB-016, SB-017): the video at the app's cut, what the
 * app heard in it, how close that is to the quote, the cut and the lower third the app made, and
 * Accept or Reject. The only thing the owner can change is the cut, one word at a time; the
 * server finds the quiet points and fills in the rest when the clip is accepted. Flags that
 * guard the meaning of the quote are shown in red and ask once more before Accept. A clip of a
 * claim that is not a sound bite is shown read-only, as context.
 */
export function SoundbiteClipPanel({ item, projectId, claim, disabled, onAccept, onReject }: Props) {
  const retry = useTranscribeEvidenceClip(projectId);
  const clip = item.soundbite;
  const isBite = claim.want === "soundbite";
  const saved = clip?.decision ?? null;
  const heard = clip?.heard ?? null;
  const words = heard?.words ?? [];
  const match = heard?.match ?? null;

  // The owner's change of the cut (first and last heard word), and whether Accept is asking
  // "Are you sure?" because a flag guards the meaning of the quote.
  const [cutWords, setCutWords] = useState<CutWords | null>(null);
  const [confirming, setConfirming] = useState(false);

  // The words of the cut: the owner's, else the accepted clip's, else the app's.
  const first = cutWords?.first_word ?? saved?.first_word ?? match?.first ?? null;
  const last = cutWords?.last_word ?? saved?.last_word ?? match?.last ?? null;
  // The words the server would use without being told (the saved ones, else the proposed ones).
  const baseFirst = saved?.first_word ?? match?.first ?? null;
  const baseLast = saved?.last_word ?? match?.last ?? null;
  const changed = first !== baseFirst || last !== baseLast;
  // A cut other than the proposed one has to be asked for: its times and its flags can differ.
  const otherThanProposed =
    match !== null && first !== null && last !== null && (first !== match.first || last !== match.last);
  const trimQuery = useSoundbiteTrim(
    projectId,
    item.item_key,
    first ?? 0,
    last ?? 0,
    isBite && otherThanProposed,
  );
  const trim = trimQuery.data;
  const trimReady = trim !== undefined && !trimQuery.isPlaceholderData;

  if (clip === null || !item.usable) {
    return null;
  }

  const status = clip.transcription.status;
  const accepted = item.verdict === "accepted";

  // The cut: for words other than the proposed ones the server's answer (once it is there), else
  // the one stored with the accepted clip, else the one the app proposed.
  const cut = isBite && otherThanProposed ? (trimReady ? trim : null) : (saved ?? clip.proposed_trim);
  const length = cut !== null ? cut.out_s - cut.in_s : null;
  const moveCut = (change: Partial<CutWords>) => {
    if (first === null || last === null) {
      return;
    }
    setConfirming(false);
    setCutWords({ first_word: change.first_word ?? first, last_word: change.last_word ?? last });
  };

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
  if (cut === null && otherThanProposed) {
    blockers.push(
      trimQuery.isError ? "the app could not find this cut" : "the cut is still being found",
    );
  } else if (cut === null) {
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

  // The flags of the cut that is shown. The admission words depend on the cut, so for a cut the
  // owner moved they come from the server's answer for it, not from the import.
  const flags = (
    otherThanProposed
      ? [
          ...clip.flags.filter((flag) => flag.code !== "admission_words"),
          ...(trimReady ? trim.flags.filter((flag) => flag.code === "admission_words") : []),
        ]
      : clip.flags
  ).filter((flag) => flag.code !== "length");
  const riskyFlags = isBite ? flags.filter((flag) => RISKY_FLAG_CODES.includes(flag.code)) : [];
  const otherFlags = flags.filter((flag) => !riskyFlags.includes(flag));

  // Accept (or saving a new cut) asks once more when a risky flag is there.
  const send = () => {
    if (riskyFlags.length > 0 && !confirming) {
      setConfirming(true);
      return;
    }
    setConfirming(false);
    onAccept(
      changed && first !== null && last !== null
        ? { first_word: first, last_word: last }
        : undefined,
    );
  };

  return (
    <Stack gap="xs">
      {riskyFlags.length > 0 && (
        <Alert color="red" p="xs" title="Check the meaning before you accept">
          <Stack gap={2}>
            {riskyFlags.map((flag) => (
              <Text key={flag.code} size="xs">
                {flag.message}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

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

      {isBite && first !== null && last !== null && words.length > 0 && (
        <Group gap="xs">
          <Button
            size="compact-xs"
            variant="default"
            disabled={disabled || first <= 0}
            onClick={() => moveCut({ first_word: first - 1 })}
          >
            Start earlier
          </Button>
          <Button
            size="compact-xs"
            variant="default"
            disabled={disabled || first >= last}
            onClick={() => moveCut({ first_word: first + 1 })}
          >
            Start later
          </Button>
          <Button
            size="compact-xs"
            variant="default"
            disabled={disabled || last <= first}
            onClick={() => moveCut({ last_word: last - 1 })}
          >
            End earlier
          </Button>
          <Button
            size="compact-xs"
            variant="default"
            disabled={disabled || last >= words.length - 1}
            onClick={() => moveCut({ last_word: last + 1 })}
          >
            End later
          </Button>
          {match !== null && otherThanProposed && (
            <Button
              size="compact-xs"
              variant="subtle"
              disabled={disabled}
              onClick={() => {
                setConfirming(false);
                setCutWords({ first_word: match.first, last_word: match.last });
              }}
            >
              Back to the proposed cut
            </Button>
          )}
        </Group>
      )}

      {isBite && trimQuery.isError && otherThanProposed && (
        <Text size="xs" c="red">
          {describeError(trimQuery.error)}
        </Text>
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

      {isBite && saved !== null && saved.rights_note !== "" && (
        <Text size="xs" c="dimmed">
          Why this clip: {saved.rights_note}
        </Text>
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
              disabled={disabled || confirming || blockers.length > 0 || (accepted && !changed)}
              onClick={send}
            >
              {accepted ? (changed ? "Save new cut" : "Accepted") : "Accept"}
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
          {confirming && (
            <Alert color="red" p="xs" title="Are you sure?">
              <Stack gap={4}>
                <Text size="xs">
                  This clip may change meaning when it is cut. Read the red notes above, then
                  decide.
                </Text>
                <Group gap="xs">
                  <Button size="compact-xs" color="red" disabled={disabled} onClick={send}>
                    Yes, accept
                  </Button>
                  <Button
                    size="compact-xs"
                    variant="default"
                    onClick={() => setConfirming(false)}
                  >
                    Cancel
                  </Button>
                </Group>
              </Stack>
            </Alert>
          )}
          {(!accepted || changed) && blockers.length > 0 && (
            <Text size="xs" c="dimmed">
              This clip cannot be accepted: {blockers.join("; ")}.
            </Text>
          )}
        </Stack>
      )}
    </Stack>
  );
}
