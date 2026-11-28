import { useState } from "react";

import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  NumberInput,
  Paper,
  Select,
  Stack,
  Switch,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  FOOTAGE_REVIEW_STEP_S,
  FOOTAGE_REVIEW_USE_MAX_S,
  FOOTAGE_REVIEW_USE_MIN_S,
  useDecideFootagePiece,
  useFinishFootageReview,
  useFootageReview,
  useReorderFootageShown,
  useRemoveOwnFootageFile,
  useSetFootageFraming,
  useSetFootageReviewNoFootage,
  useSetFootageReviewUse,
  useStartFootageReviewPreview,
  type FootageFraming,
  type FootageReviewMark,
  type FootageReviewPiece,
} from "../../api/footageReview";
import { HighlightedImage } from "./EvidenceReview";
import { FootagePreview } from "./FootagePreview";
import { safeHref } from "./safeHref";

type FootageReviewProps = {
  projectId: number;
};

const TIER_LABEL: Record<string, string> = {
  official: "Official source",
  press: "Press kit",
  commons: "Free-licence library",
  news: "News outlet",
  creator: "Creator's video",
  other: "Other source",
};

const WARNING_LABEL: Record<string, string> = {
  low_resolution: "Low resolution",
  file_footage: "File footage",
  event_not_checked: "Event not checked",
  text_on_picture: "Text on the picture",
  not_official: "Not an official source",
  channel_not_publisher: "Channel is not the publisher",
  licence_unknown: "Licence unknown",
  focus_not_found: "Focus words not found",
};

const KIND_LABEL: Record<string, string> = {
  video: "Video",
  image: "Photo",
  page: "Web page",
  pdf: "PDF page",
};

const MARK_STATUS_LABEL: Record<string, string> = {
  found: "Found",
  not_found: "Nothing found",
  blocked: "Blocked",
};

const FRAMING_OPTIONS = [
  { value: "fit", label: "Fit over a blurred copy" },
  { value: "left", label: "Crop: left" },
  { value: "centre", label: "Crop: centre" },
  { value: "right", label: "Crop: right" },
];

const TIMELINE_STYLE = {
  position: "relative",
  height: 14,
  borderRadius: 4,
  background: "var(--mantine-color-dark-6)",
  overflow: "hidden",
} as const;

function round3(value: number): number {
  return Math.round(value * 1000) / 1000;
}

function percent(seconds: number, total: number): string {
  return `${Math.min(100, Math.max(0, (seconds / total) * 100))}%`;
}

function pieceTitle(piece: FootageReviewPiece): string {
  if (piece.origin === "owner") {
    return piece.credit ? `Your file: ${piece.credit}` : "Your file";
  }
  return piece.what_it_shows ?? `Piece ${piece.piece_id}`;
}

/** Whether accepting a piece needs a second click: it shows another occasion than the words. */
function isFileFootage(piece: FootageReviewPiece): boolean {
  return piece.same_event === "no";
}

// --- A video's start and end -----------------------------------------------------------------

type UseControlsProps = {
  piece: FootageReviewPiece;
  disabled: boolean;
  onChange: (startS: number, endS: number) => void;
};

/**
 * Where an agent's video starts and ends: a timeline with the part shown, the cuts and the
 * moment the agent chose, boxes for the times, and buttons that move an end by half a second or
 * to the edge of the shot. A button that would break the 2 to 15 second rule is disabled; the
 * server checks it again.
 */
function UseControls({ piece, disabled, onChange }: UseControlsProps) {
  const use = piece.use;
  const windowS = piece.window_s;
  const [start, setStart] = useState<number | string>(use?.start_s ?? 0);
  const [end, setEnd] = useState<number | string>(use?.end_s ?? 0);
  if (!use || windowS === null || windowS <= 0) {
    return null;
  }

  function fits(startS: number, endS: number): boolean {
    const length = endS - startS;
    return (
      startS >= 0 &&
      windowS !== null &&
      endS <= windowS + 0.0015 &&
      length >= FOOTAGE_REVIEW_USE_MIN_S - 0.0015 &&
      length <= FOOTAGE_REVIEW_USE_MAX_S + 0.0015
    );
  }

  function commitBoxes() {
    if (typeof start === "number" && typeof end === "number" && use) {
      if (start !== use.start_s || end !== use.end_s) {
        onChange(round3(start), round3(end));
      }
    }
  }

  const total = windowS;
  const cuts = [...piece.cuts].sort((a, b) => a - b);
  const earlierCut = [...cuts]
    .reverse()
    .find((cut) => cut < use.start_s - 0.001);
  const laterCut = cuts.find((cut) => cut > use.end_s + 0.001);
  const moves = [
    {
      label: "Start 0.5 s earlier",
      start: round3(use.start_s - FOOTAGE_REVIEW_STEP_S),
      end: use.end_s,
    },
    {
      label: "Start 0.5 s later",
      start: round3(use.start_s + FOOTAGE_REVIEW_STEP_S),
      end: use.end_s,
    },
    {
      label: "Start at the shot's start",
      start: round3(earlierCut ?? 0),
      end: use.end_s,
    },
    {
      label: "End 0.5 s earlier",
      start: use.start_s,
      end: round3(use.end_s - FOOTAGE_REVIEW_STEP_S),
    },
    {
      label: "End 0.5 s later",
      start: use.start_s,
      end: round3(use.end_s + FOOTAGE_REVIEW_STEP_S),
    },
    {
      label: "End at the shot's end",
      start: use.start_s,
      end: round3(laterCut ?? total),
    },
  ];

  return (
    <Stack gap={4}>
      <div style={TIMELINE_STYLE} role="img" aria-label="The video's timeline">
        <div
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: percent(use.start_s, total),
            width: percent(use.end_s - use.start_s, total),
            background: "rgba(34, 139, 230, 0.55)",
          }}
        />
        {cuts.map((cut) => (
          <div
            key={cut}
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: percent(cut, total),
              width: 2,
              background: "#fa5252",
            }}
          />
        ))}
        {piece.moment_s !== null && (
          <div
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: percent(piece.moment_s, total),
              width: 3,
              background: "#fcc419",
            }}
          />
        )}
      </div>
      <Text size="xs" c="dimmed">
        Blue: the part shown. Red lines: cuts. Yellow: the moment the agent
        chose. The video is {total.toFixed(1)} s long.
      </Text>
      <Group gap="xs" wrap="nowrap" align="flex-end">
        <NumberInput
          size="xs"
          w={110}
          label="Starts at (s)"
          min={0}
          max={total}
          step={FOOTAGE_REVIEW_STEP_S}
          decimalScale={3}
          value={start}
          disabled={disabled}
          onChange={setStart}
          onBlur={commitBoxes}
        />
        <NumberInput
          size="xs"
          w={110}
          label="Ends at (s)"
          min={0}
          max={total}
          step={FOOTAGE_REVIEW_STEP_S}
          decimalScale={3}
          value={end}
          disabled={disabled}
          onChange={setEnd}
          onBlur={commitBoxes}
        />
        <Text size="xs" c="dimmed" pb={6}>
          {(use.end_s - use.start_s).toFixed(1)} s (2 to 15 s)
        </Text>
      </Group>
      <Group gap={4}>
        {moves.map((move) => (
          <Button
            key={move.label}
            size="compact-xs"
            variant="default"
            disabled={
              disabled ||
              !fits(move.start, move.end) ||
              (move.start === use.start_s && move.end === use.end_s)
            }
            onClick={() => onChange(move.start, move.end)}
          >
            {move.label}
          </Button>
        ))}
      </Group>
    </Stack>
  );
}

// --- One piece -------------------------------------------------------------------------------

function SourceLine({ piece }: { piece: FootageReviewPiece }) {
  const source = piece.source;
  if (source === null) {
    return null;
  }
  const href = safeHref(source.final_url) ?? safeHref(source.url);
  const name = source.title ?? source.publisher ?? "Source";
  return (
    <Text size="sm">
      {source.publisher !== null && source.title !== null
        ? `${source.publisher}: `
        : ""}
      {href !== null ? (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {name}
        </a>
      ) : (
        name
      )}
      {source.published !== null ? `, ${source.published}` : ""}
      {source.licence !== null ? `. Licence: ${source.licence}` : ""}
    </Text>
  );
}

function PieceMedia({ piece }: { piece: FootageReviewPiece }) {
  if (piece.kind === "video" && piece.video_url !== null) {
    const start = piece.use?.start_s ?? 0;
    const end = piece.use?.end_s;
    return (
      <Stack gap={4}>
        <video
          src={
            end !== undefined
              ? `${piece.video_url}#t=${start},${end}`
              : piece.video_url
          }
          controls
          muted
          preload="metadata"
          style={{
            maxWidth: "100%",
            maxHeight: 240,
            borderRadius: 4,
            background: "#000",
          }}
        />
        {piece.strip_url !== null && (
          <img
            src={piece.strip_url}
            alt="Frames of the video, half a second apart"
            loading="lazy"
            style={{ maxWidth: "100%", borderRadius: 4 }}
          />
        )}
      </Stack>
    );
  }
  if (piece.image_url !== null) {
    return (
      <HighlightedImage
        url={piece.image_url}
        rects={piece.kind === "image" ? [] : piece.focus_rects}
        alt={piece.what_it_shows ?? "The picture"}
        maxHeight={piece.kind === "image" ? 240 : 320}
      />
    );
  }
  return null;
}

type PieceCardProps = {
  piece: FootageReviewPiece;
  live: boolean;
  disabled: boolean;
  previewStarting: boolean;
  onAccept: (piece: FootageReviewPiece) => void;
  onReject: (piece: FootageReviewPiece) => void;
  onUse: (piece: FootageReviewPiece, startS: number, endS: number) => void;
  onPreview: (piece: FootageReviewPiece) => void;
};

function PieceCard({
  piece,
  live,
  disabled,
  previewStarting,
  onAccept,
  onReject,
  onUse,
  onPreview,
}: PieceCardProps) {
  const acting = disabled || !live;
  return (
    <Paper withBorder p="sm" radius="sm">
      <Stack gap="xs">
        <Group gap="xs">
          <Badge variant="light" color="gray">
            {KIND_LABEL[piece.kind ?? ""] ?? "Piece"} {piece.piece_id}
          </Badge>
          {piece.tier !== null && (
            <Badge
              variant="light"
              color={piece.tier === "official" ? "green" : "gray"}
            >
              {TIER_LABEL[piece.tier] ?? piece.tier}
            </Badge>
          )}
          {piece.verdict === "accepted" && (
            <Badge variant="light" color="green">
              Accepted
            </Badge>
          )}
          {piece.verdict === "rejected" && (
            <Badge variant="light" color="red">
              Rejected
            </Badge>
          )}
          {piece.verdict === null && piece.usable && (
            <Badge variant="light" color="orange">
              Not decided
            </Badge>
          )}
          {piece.warnings.map((warning) => (
            <Badge
              key={warning.code}
              variant="outline"
              color="orange"
              title={warning.message}
            >
              {WARNING_LABEL[warning.code] ?? warning.code}
            </Badge>
          ))}
        </Group>

        {!piece.usable && (
          <Stack gap={2}>
            <Text size="xs" c="red">
              This piece did not pass the checks and cannot be used.
            </Text>
            {piece.reasons.map((text) => (
              <Text key={text} size="xs" c="red">
                {text}
              </Text>
            ))}
          </Stack>
        )}

        {piece.usable && <PieceMedia piece={piece} />}

        {piece.what_it_shows !== null && (
          <Text size="sm">{piece.what_it_shows}</Text>
        )}
        <SourceLine piece={piece} />
        {(piece.same_event !== null || piece.event_date !== null) && (
          <Text size="xs" c="dimmed">
            {piece.same_event === "yes" && "The event the words describe"}
            {piece.same_event === "no" && "Another occasion (file footage)"}
            {piece.same_event === "unknown" &&
              "Not checked whether it is the same event"}
            {piece.event_date !== null
              ? `. Event date: ${piece.event_date}`
              : ""}
          </Text>
        )}
        {piece.warnings.map((warning) => (
          <Text key={`w-${warning.code}`} size="xs" c="orange">
            {warning.message}
          </Text>
        ))}

        {piece.usable && piece.kind === "video" && (
          <UseControls
            // A new start or end from the server resets the boxes.
            key={`${piece.item_key}-${piece.use?.start_s}-${piece.use?.end_s}`}
            piece={piece}
            disabled={acting}
            onChange={(startS, endS) => onUse(piece, startS, endS)}
          />
        )}

        {piece.usable && (
          <Group gap="xs">
            <Button
              size="xs"
              color="green"
              variant={piece.verdict === "accepted" ? "filled" : "light"}
              disabled={acting || piece.verdict === "accepted"}
              onClick={() => onAccept(piece)}
            >
              Accept
            </Button>
            <Button
              size="xs"
              color="red"
              variant={piece.verdict === "rejected" ? "filled" : "light"}
              disabled={acting || piece.verdict === "rejected"}
              onClick={() => onReject(piece)}
            >
              Reject
            </Button>
          </Group>
        )}
        {piece.usable && (
          <FootagePreview
            preview={piece.preview}
            disabled={disabled}
            starting={previewStarting}
            onStart={() => onPreview(piece)}
          />
        )}
      </Stack>
    </Paper>
  );
}

// --- One mark --------------------------------------------------------------------------------

type MarkReviewProps = {
  mark: FootageReviewMark;
  portrait: boolean;
  disabled: boolean;
  previewStartingKey: string | null;
  onAccept: (piece: FootageReviewPiece) => void;
  onReject: (piece: FootageReviewPiece) => void;
  onUse: (piece: FootageReviewPiece, startS: number, endS: number) => void;
  onPreview: (piece: FootageReviewPiece) => void;
  onMove: (mark: FootageReviewMark, index: number, direction: -1 | 1) => void;
  onRemoveShown: (piece: FootageReviewPiece) => void;
  onNoFootage: (mark: FootageReviewMark, value: boolean) => void;
  onFraming: (mark: FootageReviewMark, framing: FootageFraming | null) => void;
};

function MarkReview({
  mark,
  portrait,
  disabled,
  previewStartingKey,
  onAccept,
  onReject,
  onUse,
  onPreview,
  onMove,
  onRemoveShown,
  onNoFootage,
  onFraming,
}: MarkReviewProps) {
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Group gap="xs">
              <Text size="sm" fw={700}>
                {mark.id}
              </Text>
              {mark.status !== null && (
                <Badge
                  size="sm"
                  variant="light"
                  color={mark.status === "found" ? "green" : "gray"}
                >
                  {MARK_STATUS_LABEL[mark.status] ?? mark.status}
                </Badge>
              )}
              {mark.live && mark.undecided > 0 && (
                <Badge size="sm" variant="light" color="orange">
                  {mark.undecided} not decided
                </Badge>
              )}
            </Group>
            <Text size="sm">{mark.text}</Text>
            {mark.note !== "" && (
              <Text size="xs" c="dimmed">
                Note: {mark.note}
              </Text>
            )}
            {mark.summary !== "" && (
              <Text size="xs">Agent: {mark.summary}</Text>
            )}
          </Stack>
          <Switch
            label="No footage here"
            checked={mark.no_footage}
            disabled={disabled}
            onChange={(event) => onNoFootage(mark, event.currentTarget.checked)}
          />
        </Group>

        {!mark.live && (
          <Alert color="yellow" p="xs">
            The words or the note of this mark changed since the round was
            written, so its pieces cannot be decided on. Write a new round to
            research it again.
          </Alert>
        )}

        {mark.attempts.length > 0 && mark.pieces.length === 0 && (
          <Stack gap={2}>
            <Text size="xs" fw={600}>
              What the agent tried
            </Text>
            {mark.attempts.map((attempt, index) => (
              <Text key={index} size="xs" c="dimmed">
                {attempt.what}: {attempt.outcome}
              </Text>
            ))}
          </Stack>
        )}

        {portrait && (
          <Select
            size="xs"
            w={240}
            label="Portrait framing"
            allowDeselect={false}
            data={FRAMING_OPTIONS}
            value={mark.framing ?? "fit"}
            disabled={disabled}
            onChange={(value) =>
              onFraming(
                mark,
                value === null || value === "fit"
                  ? null
                  : (value as FootageFraming),
              )
            }
          />
        )}

        <Stack gap={4}>
          <Text size="xs" fw={600}>
            Shown on video, in order
          </Text>
          {mark.no_footage && (
            <Text size="xs" c="dimmed">
              No footage here: the shots already planned stay.
            </Text>
          )}
          {!mark.no_footage && mark.shown.length === 0 && (
            <Text size="xs" c="dimmed">
              Nothing is shown yet. Accept a piece below or add a file of your
              own on the mark.
            </Text>
          )}
          {mark.shown.map((piece, index) => (
            <Group key={piece.item_key} gap="xs" wrap="nowrap">
              <Text size="xs" w={16}>
                {index + 1}.
              </Text>
              <Badge
                size="sm"
                variant="light"
                color={piece.origin === "owner" ? "blue" : "gray"}
              >
                {KIND_LABEL[piece.kind ?? ""] ?? "Piece"}
              </Badge>
              <Text size="xs" lineClamp={1} style={{ flex: 1, minWidth: 0 }}>
                {pieceTitle(piece)}
              </Text>
              <Button
                size="compact-xs"
                variant="default"
                disabled={disabled || index === 0}
                onClick={() => onMove(mark, index, -1)}
              >
                Up
              </Button>
              <Button
                size="compact-xs"
                variant="default"
                disabled={disabled || index === mark.shown.length - 1}
                onClick={() => onMove(mark, index, 1)}
              >
                Down
              </Button>
              <Button
                size="compact-xs"
                variant="default"
                disabled={disabled}
                onClick={() => onRemoveShown(piece)}
              >
                Remove
              </Button>
            </Group>
          ))}
        </Stack>

        {mark.pieces.length > 0 && (
          <Stack gap="xs">
            <Text size="xs" fw={600}>
              What the research found
            </Text>
            {mark.pieces.map((piece) => (
              <PieceCard
                key={piece.item_key}
                piece={piece}
                live={mark.live}
                disabled={disabled}
                previewStarting={previewStartingKey === piece.item_key}
                onAccept={onAccept}
                onReject={onReject}
                onUse={onUse}
                onPreview={onPreview}
              />
            ))}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}

// --- The review ------------------------------------------------------------------------------

/**
 * The review of the footage the research found (FTG-012): for each mark, accept or reject each
 * piece, put what is shown in order, move a video's start and end, choose the portrait crop or
 * "no footage here", then press Review done. Every text of the agent is shown as plain text.
 */
export function FootageReview({ projectId }: FootageReviewProps) {
  const { data, isLoading, isError, error } = useFootageReview(projectId);
  const decide = useDecideFootagePiece(projectId);
  const setUse = useSetFootageReviewUse(projectId);
  const setFraming = useSetFootageFraming(projectId);
  const setNoFootage = useSetFootageReviewNoFootage(projectId);
  const reorder = useReorderFootageShown(projectId);
  const removeOwn = useRemoveOwnFootageFile(projectId);
  const startPreview = useStartFootageReviewPreview(projectId);
  const finish = useFinishFootageReview(projectId);
  const [confirming, setConfirming] = useState<FootageReviewPiece | null>(null);

  const mutations = [
    decide,
    setUse,
    setFraming,
    setNoFootage,
    reorder,
    removeOwn,
    finish,
  ];
  const busy =
    mutations.some((mutation) => mutation.isPending) ||
    data?.importing === true;

  function resetErrors() {
    for (const mutation of [...mutations, startPreview]) {
      mutation.reset();
    }
  }

  function accept(piece: FootageReviewPiece) {
    if (isFileFootage(piece)) {
      setConfirming(piece);
      return;
    }
    resetErrors();
    decide.mutate({ itemKey: piece.item_key, verdict: "accepted" });
  }

  function reject(piece: FootageReviewPiece) {
    resetErrors();
    decide.mutate({ itemKey: piece.item_key, verdict: "rejected" });
  }

  function move(mark: FootageReviewMark, index: number, direction: -1 | 1) {
    resetErrors();
    const keys = mark.shown.map((piece) => piece.item_key);
    const target = index + direction;
    [keys[index], keys[target]] = [keys[target], keys[index]];
    reorder.mutate({ markId: mark.id, shown: keys });
  }

  function removeShown(piece: FootageReviewPiece) {
    resetErrors();
    if (piece.origin === "owner") {
      removeOwn.mutate(piece.item_key);
    } else {
      decide.mutate({ itemKey: piece.item_key, verdict: "rejected" });
    }
  }

  if (isLoading) {
    return <Loader size="sm" />;
  }
  if (isError) {
    return (
      <Alert color="red" title="Could not load the footage review">
        {describeError(error)}
      </Alert>
    );
  }
  if (data === undefined || !data.wanted || data.marks.length === 0) {
    return null;
  }

  const reviewed = data.status === "reviewed";
  const failed = mutations.find((mutation) => mutation.isError);

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="center">
        <Group gap="xs">
          <Title order={5}>Review the footage</Title>
          {data.round_id !== null && (
            <Badge variant="light" color={reviewed ? "green" : "orange"}>
              {data.round_id}, import {data.import_version}:{" "}
              {reviewed ? "Reviewed" : "Not reviewed yet"}
            </Badge>
          )}
          {data.undecided > 0 && (
            <Badge variant="light" color="orange">
              {data.undecided} not decided
            </Badge>
          )}
        </Group>
        <Button
          onClick={() => finish.mutate()}
          loading={finish.isPending}
          disabled={!data.can_finish || busy}
        >
          Review done
        </Button>
      </Group>
      {!data.can_finish && data.finish_blocked_reason !== null && (
        <Text size="xs" c="dimmed">
          {data.finish_blocked_reason}
        </Text>
      )}

      {data.marks.map((mark) => (
        <MarkReview
          key={mark.id}
          mark={mark}
          portrait={data.orientation === "portrait"}
          disabled={busy}
          previewStartingKey={
            startPreview.isPending ? (startPreview.variables ?? null) : null
          }
          onAccept={accept}
          onReject={reject}
          onUse={(piece, startS, endS) => {
            resetErrors();
            setUse.mutate({ itemKey: piece.item_key, startS, endS });
          }}
          onPreview={(piece) => {
            resetErrors();
            startPreview.mutate(piece.item_key);
          }}
          onMove={move}
          onRemoveShown={removeShown}
          onNoFootage={(target, value) => {
            resetErrors();
            setNoFootage.mutate({ markId: target.id, noFootage: value });
          }}
          onFraming={(target, framing) => {
            resetErrors();
            setFraming.mutate({ markId: target.id, framing });
          }}
        />
      ))}

      {failed?.isError === true && (
        <Alert color="red" title="The change was not saved">
          {describeError(failed.error)}
        </Alert>
      )}
      {startPreview.isError && (
        <Alert color="red" title="The preview was not started">
          {describeError(startPreview.error)}
        </Alert>
      )}

      <Modal
        opened={confirming !== null}
        onClose={() => setConfirming(null)}
        title="Show file footage?"
      >
        <Stack gap="sm">
          <Text size="sm">
            This piece is footage of another occasion, not of the event the
            words describe. Show it only if the sentence can carry it.
          </Text>
          {confirming?.what_it_shows != null && (
            <Text size="sm">{confirming.what_it_shows}</Text>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
            <Button
              color="green"
              onClick={() => {
                if (confirming !== null) {
                  resetErrors();
                  decide.mutate({
                    itemKey: confirming.item_key,
                    verdict: "accepted",
                  });
                }
                setConfirming(null);
              }}
            >
              Accept anyway
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
