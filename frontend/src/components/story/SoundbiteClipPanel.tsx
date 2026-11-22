import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useState } from "react";

import { describeError } from "../../api/errors";
import {
  useSoundbiteTrim,
  useTranscribeEvidenceClip,
  type EvidenceReviewItem,
  type SoundbiteDecision,
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

// The server checks all of these again; they only keep the buttons honest.
const MIN_CLIP_S = 3;
const MAX_CLIP_S = 15;
const SPEAKER_MAX = 100;
const LINE_MAX = 80;
const NOTE_MAX = 300;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function seconds(value: number): string {
  return `${value.toFixed(2)} s`;
}

/** The fields the owner fills in, as the screen holds them. */
type Fields = {
  speaker: string;
  role: string;
  venue: string;
  recorded: string;
  dateConfirmed: boolean;
  acknowledged: string[];
  rightsNote: string;
};

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
  // Accepts the clip with these details, or saves new details of an accepted clip.
  onAccept: (details: SoundbiteDecision) => void;
  onReject: () => void;
};

function sameList(a: string[], b: string[]): boolean {
  return a.length === b.length && [...a].sort().every((value, index) => value === [...b].sort()[index]);
}

/**
 * A sound bite clip in the review (SB-006, SB-007): the video with its cut, what the app heard
 * in it, how close that is to the quote, the cut moved word by word, the lower third's lines, the
 * recording date, the flags and the rights note. The cut is found by the server in the clip's
 * own audio; the browser only says which words the clip starts and ends with. A clip of a claim
 * that is not a sound bite is shown read-only, as context.
 */
export function SoundbiteClipPanel({ item, projectId, claim, disabled, onAccept, onReject }: Props) {
  const retry = useTranscribeEvidenceClip(projectId);
  const clip = item.soundbite;
  const isBite = claim.want === "soundbite";
  const saved = clip?.decision ?? null;
  const heard = clip?.heard ?? null;
  const words = heard?.words ?? [];
  const match = heard?.match ?? null;

  // The owner's changes only; what is not changed reads from the saved decision, else from the
  // proposal, so nothing has to be copied when the clip is heard late or saved.
  const [cutWords, setCutWords] = useState<{ first: number; last: number } | null>(null);
  const [edits, setEdits] = useState<Partial<Fields>>({});

  const first = cutWords?.first ?? saved?.first_word ?? match?.first ?? null;
  const last = cutWords?.last ?? saved?.last_word ?? match?.last ?? null;
  const published = item.source?.published ?? "";
  const fields: Fields = {
    speaker: edits.speaker ?? saved?.speaker ?? claim.speaker ?? "",
    role: edits.role ?? saved?.role ?? "",
    venue: edits.venue ?? saved?.venue ?? "",
    recorded: edits.recorded ?? saved?.recorded ?? (DATE_PATTERN.test(published) ? published : ""),
    dateConfirmed: edits.dateConfirmed ?? saved !== null,
    acknowledged: edits.acknowledged ?? saved?.acknowledged_flags ?? [],
    rightsNote: edits.rightsNote ?? saved?.rights_note ?? "",
  };
  const edit = (change: Partial<Fields>) => setEdits((current) => ({ ...current, ...change }));

  const trimQuery = useSoundbiteTrim(
    projectId,
    item.item_key,
    first ?? 0,
    last ?? 0,
    isBite && first !== null && last !== null,
  );
  const trim = trimQuery.data;
  const trimReady = trim !== undefined && !trimQuery.isPlaceholderData;

  if (clip === null || !item.usable) {
    return null;
  }
  const status = clip.transcription.status;
  const proposed = clip.proposed_trim;
  const accepted = item.verdict === "accepted";

  const moveCut = (change: { first?: number; last?: number }) => {
    if (first === null || last === null) {
      return;
    }
    setCutWords({ first: change.first ?? first, last: change.last ?? last });
  };

  // The flags to tick: the ones stored at import that are asked for, and the ones that depend on
  // the cut being tried (the admission words).
  const askedFlags = [
    ...clip.flags.filter((flag) => flag.acknowledge),
    ...(trimReady ? trim.flags.filter((flag) => flag.acknowledge) : []),
  ].filter((flag, index, all) => all.findIndex((other) => other.code === flag.code) === index);
  const otherFlags = clip.flags.filter((flag) => !flag.acknowledge && flag.code !== "length");
  const askedCodes = askedFlags.map((flag) => flag.code);
  const ticked = fields.acknowledged.filter((code) => askedCodes.includes(code));

  const needsNote = clip.licence !== "creative_commons";
  const length = trimReady ? trim.length_s : null;
  const missing: string[] = [];
  if (words.length === 0) {
    missing.push("the clip has to be heard first");
  }
  if (clip.fidelity !== "exact" && clip.fidelity !== "near") {
    missing.push("the clip's words have to be the quote's words");
  }
  if (!trimReady) {
    missing.push("the cut is still being found");
  } else if (length !== null && (length < MIN_CLIP_S || length > MAX_CLIP_S)) {
    missing.push(`the cut has to be ${MIN_CLIP_S} to ${MAX_CLIP_S} s`);
  }
  if (fields.speaker.trim() === "" || fields.speaker.length > SPEAKER_MAX) {
    missing.push("the speaker's name");
  }
  if (fields.role.trim() === "" || fields.role.length > LINE_MAX) {
    missing.push("the role at the time");
  }
  if (fields.venue.trim() === "" || fields.venue.length > LINE_MAX) {
    missing.push("the venue or event");
  }
  if (!DATE_PATTERN.test(fields.recorded)) {
    missing.push("the recording date");
  } else if (!fields.dateConfirmed) {
    missing.push("a confirmed recording date");
  }
  if (askedCodes.some((code) => !ticked.includes(code))) {
    missing.push("every flag ticked");
  }
  if (needsNote && fields.rightsNote.trim() === "") {
    missing.push("a rights note");
  }

  const details: SoundbiteDecision | null =
    first !== null && last !== null
      ? {
          first_word: first,
          last_word: last,
          speaker: fields.speaker.trim(),
          role: fields.role.trim(),
          venue: fields.venue.trim(),
          recorded: fields.recorded,
          acknowledged_flags: ticked,
          rights_note: fields.rightsNote.trim(),
        }
      : null;
  const dirty =
    saved === null ||
    details === null ||
    details.first_word !== saved.first_word ||
    details.last_word !== saved.last_word ||
    details.speaker !== saved.speaker ||
    details.role !== saved.role ||
    details.venue !== saved.venue ||
    details.recorded !== saved.recorded ||
    details.rights_note !== saved.rights_note ||
    !sameList(details.acknowledged_flags, saved.acknowledged_flags);

  const quoteSpan =
    match !== null && words[match.first] !== undefined && words[match.last] !== undefined
      ? { start: words[match.first].start, end: words[match.last].end }
      : null;
  const cutSpan = isBite && trimReady ? { start: trim.in_s, end: trim.out_s } : null;

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

      {!isBite && proposed !== null && (
        <Text size="xs" c="dimmed">
          Proposed cut: {seconds(proposed.in_s)} to {seconds(proposed.out_s)} of the clip
          {proposed.in_clean && proposed.out_clean ? "" : " (an edge is not in a quiet gap)"}
        </Text>
      )}

      {!isBite && (
        <Text size="xs" c="dimmed">
          This claim is not a sound bite, so the video is context only: it can be accepted for
          the description&apos;s sources, but it is never shown on video.
        </Text>
      )}

      {isBite && first !== null && last !== null && words.length > 0 && (
        <Stack gap={4}>
          <Text size="xs" fw={600}>
            The cut
          </Text>
          <Group gap="xs">
            <Button
              size="compact-xs"
              variant="default"
              disabled={disabled || first <= 0}
              onClick={() => moveCut({ first: first - 1 })}
            >
              Start earlier
            </Button>
            <Button
              size="compact-xs"
              variant="default"
              disabled={disabled || first >= last}
              onClick={() => moveCut({ first: first + 1 })}
            >
              Start later
            </Button>
            <Button
              size="compact-xs"
              variant="default"
              disabled={disabled || last <= first}
              onClick={() => moveCut({ last: last - 1 })}
            >
              End earlier
            </Button>
            <Button
              size="compact-xs"
              variant="default"
              disabled={disabled || last >= words.length - 1}
              onClick={() => moveCut({ last: last + 1 })}
            >
              End later
            </Button>
            {match !== null && (first !== match.first || last !== match.last) && (
              <Button
                size="compact-xs"
                variant="subtle"
                disabled={disabled}
                onClick={() => setCutWords({ first: match.first, last: match.last })}
              >
                Back to the proposed cut
              </Button>
            )}
          </Group>
          {trimQuery.isError && (
            <Text size="xs" c="red">
              {describeError(trimQuery.error)}
            </Text>
          )}
          {trim !== undefined && (
            <Stack gap={2}>
              <Group gap="xs">
                {trimQuery.isFetching && <Loader size="xs" />}
                <Text
                  size="sm"
                  c={length !== null && (length < MIN_CLIP_S || length > MAX_CLIP_S) ? "red" : undefined}
                >
                  {seconds(trim.in_s)} to {seconds(trim.out_s)}, {trim.length_s.toFixed(1)} s (a
                  sound bite is {MIN_CLIP_S} to {MAX_CLIP_S} s)
                </Text>
              </Group>
              <Text size="xs" c={trim.in_clean ? "dimmed" : "orange"}>
                Start: {trim.in_clean ? "in a quiet gap" : "not in a quiet gap. Listen to it."}
              </Text>
              <Text size="xs" c={trim.out_clean ? "dimmed" : "orange"}>
                End: {trim.out_clean ? "in a quiet gap" : "not in a quiet gap. Listen to it."}
              </Text>
              {trim.warnings.map((text) => (
                <Text key={text} size="xs" c="orange">
                  {text}
                </Text>
              ))}
            </Stack>
          )}
        </Stack>
      )}

      {isBite && (
        <Stack gap="xs">
          <Text size="xs" fw={600}>
            Lower third and recording date
          </Text>
          <Group grow align="flex-start">
            <TextInput
              size="xs"
              label="Name"
              value={fields.speaker}
              maxLength={SPEAKER_MAX}
              disabled={disabled}
              onChange={(event) => edit({ speaker: event.currentTarget.value })}
            />
            <TextInput
              size="xs"
              label="Role at the time"
              placeholder="CEO, Nvidia"
              value={fields.role}
              maxLength={LINE_MAX}
              disabled={disabled}
              onChange={(event) => edit({ role: event.currentTarget.value })}
            />
            <TextInput
              size="xs"
              label="Venue or event"
              placeholder="SIEPR Economic Summit"
              value={fields.venue}
              maxLength={LINE_MAX}
              disabled={disabled}
              onChange={(event) => edit({ venue: event.currentTarget.value })}
            />
          </Group>
          <Group align="flex-end">
            <TextInput
              size="xs"
              type="date"
              label="Recording date"
              value={fields.recorded}
              max={clip.upload_date ?? undefined}
              disabled={disabled}
              onChange={(event) =>
                edit({ recorded: event.currentTarget.value, dateConfirmed: false })
              }
            />
            <Checkbox
              size="xs"
              label="This is when it was recorded, not when it was uploaded"
              checked={fields.dateConfirmed}
              disabled={disabled || !DATE_PATTERN.test(fields.recorded)}
              onChange={(event) => edit({ dateConfirmed: event.currentTarget.checked })}
            />
          </Group>
          {published === "" && (
            <Text size="xs" c="orange">
              The agent found no recording date. Find it (the event&apos;s own page) before you
              confirm one.
            </Text>
          )}
        </Stack>
      )}

      {otherFlags.map((flag) => (
        <Text key={flag.code} size="xs" c="orange">
          {flag.message}
        </Text>
      ))}

      {isBite && askedFlags.length > 0 && (
        <Stack gap={4}>
          <Text size="xs" fw={600}>
            Flags to check. Tick each one when you have checked it.
          </Text>
          {askedFlags.map((flag) => (
            <Checkbox
              key={flag.code}
              size="xs"
              label={flag.message}
              checked={ticked.includes(flag.code)}
              disabled={disabled}
              onChange={(event) =>
                edit({
                  acknowledged: event.currentTarget.checked
                    ? [...ticked, flag.code]
                    : ticked.filter((code) => code !== flag.code),
                })
              }
            />
          ))}
        </Stack>
      )}
      {!isBite &&
        clip.flags.map((flag) => (
          <Text key={flag.code} size="xs" c="orange">
            {flag.message}
          </Text>
        ))}

      {isBite && needsNote && (
        <Textarea
          size="xs"
          label="Rights note"
          description="One line: why showing this clip is fair or permitted (the licence is not Creative Commons)."
          autosize
          minRows={1}
          maxRows={3}
          maxLength={NOTE_MAX}
          value={fields.rightsNote}
          disabled={disabled}
          onChange={(event) => edit({ rightsNote: event.currentTarget.value })}
        />
      )}

      {isBite && (
        <Stack gap={4}>
          <Group gap="sm">
            {accepted ? (
              <Button
                size="xs"
                color="green"
                disabled={disabled || missing.length > 0 || !dirty || details === null}
                onClick={() => details !== null && onAccept(details)}
              >
                Save changes
              </Button>
            ) : (
              <Button
                size="xs"
                color="green"
                variant="light"
                disabled={disabled || missing.length > 0 || details === null}
                onClick={() => details !== null && onAccept(details)}
              >
                Accept
              </Button>
            )}
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
          {missing.length > 0 && (
            <Text size="xs" c="dimmed">
              To accept this clip: {missing.join("; ")}.
            </Text>
          )}
        </Stack>
      )}
    </Stack>
  );
}
