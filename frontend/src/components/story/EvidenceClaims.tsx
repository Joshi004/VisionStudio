import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  EVIDENCE_KINDS,
  useEditEvidenceClaim,
  useEvidenceClaims,
  useMarkEvidenceClaim,
  useRemoveEvidenceClaim,
  useSuggestEvidenceClaims,
  type EvidenceClaim,
  type EvidenceClaimEdit,
} from "../../api/evidenceClaims";
import { isJobActive } from "../../api/polling";
import type { ProjectDetail } from "../../api/projects";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { SoundbiteControls } from "./SoundbiteControls";
import { buildPositions, unitOffset, type Positions } from "./storyMarks";

/** A part of the story: plain, or marked as a claim. `start` is a unit position. */
type Segment = { start: number; text: string; claim: EvidenceClaim | null };

function buildSegments(text: string, claims: EvidenceClaim[], positions: Positions): Segment[] {
  const segments: Segment[] = [];
  let cursor = 0;
  // A dropped proposal, and a claim whose words are gone, are not marked in the story.
  const shown = claims
    .filter((claim) => claim.kept !== false && !claim.words_changed)
    .sort((a, b) => a.start - b.start);
  for (const claim of shown) {
    const start = positions.toUnit[claim.start];
    const end = positions.toUnit[claim.end];
    if (start === undefined || end === undefined || start < cursor || end <= start) {
      continue;
    }
    if (start > cursor) {
      segments.push({ start: cursor, text: text.slice(cursor, start), claim: null });
    }
    segments.push({ start, text: text.slice(start, end), claim });
    cursor = end;
  }
  if (cursor < text.length) {
    segments.push({ start: cursor, text: text.slice(cursor), claim: null });
  }
  return segments;
}

function markBackground(claim: EvidenceClaim, active: boolean): string {
  const colour = claim.kept === null ? "blue" : "teal";
  return `var(--mantine-color-${colour}-${active ? "filled" : "light"})`;
}

const AUTOMATIC = "auto";
const KIND_OPTIONS = [
  { value: AUTOMATIC, label: "Kind: automatic" },
  ...EVIDENCE_KINDS.map((kind) => ({ value: kind.value, label: kind.label })),
];

type Pending = { start: number; end: number; text: string };

type CardProps = {
  claim: EvidenceClaim;
  active: boolean;
  busy: boolean;
  onSelect: () => void;
  onEdit: (edit: EvidenceClaimEdit) => void;
  onRemove: () => void;
};

function ClaimCard({ claim, active, busy, onSelect, onEdit, onRemove }: CardProps) {
  const [hint, setHint] = useState(claim.hint);
  const isOwner = claim.origin === "owner";
  const dropped = claim.kept === false;
  return (
    <Paper
      withBorder
      p="sm"
      radius="sm"
      onClick={onSelect}
      style={{ borderColor: active ? "var(--mantine-color-blue-filled)" : undefined }}
    >
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <Badge color={isOwner ? "teal" : "blue"} variant="light">
              {isOwner ? "You" : "GLM"}
            </Badge>
            {claim.origin === "glm" && claim.kept === null && (
              <Badge color="gray" variant="outline">
                To decide
              </Badge>
            )}
            {dropped && (
              <Badge color="gray" variant="outline">
                Dropped
              </Badge>
            )}
            {claim.want === "soundbite" && !dropped && (
              <Badge color="grape" variant="light">
                {claim.want_by === "glm" ? "Sound bite · GLM" : "Sound bite"}
              </Badge>
            )}
            <Text size="sm" fw={500} style={{ whiteSpace: "pre-wrap" }}>
              {claim.text}
            </Text>
          </Group>
          <Group gap="xs" wrap="nowrap">
            {isOwner ? (
              <Button size="compact-sm" variant="default" onClick={onRemove} disabled={busy}>
                Remove
              </Button>
            ) : (
              <>
                {claim.kept !== true && (
                  <Button
                    size="compact-sm"
                    onClick={() => onEdit({ kept: true })}
                    disabled={busy || claim.words_changed}
                  >
                    {dropped ? "Keep again" : "Keep"}
                  </Button>
                )}
                {claim.kept !== false && (
                  <Button
                    size="compact-sm"
                    variant="default"
                    onClick={() => onEdit({ kept: false })}
                    disabled={busy}
                  >
                    Drop
                  </Button>
                )}
              </>
            )}
          </Group>
        </Group>
        {claim.reason !== "" && (
          <Text size="xs" c="dimmed">
            {claim.reason}
          </Text>
        )}
        {claim.want === "soundbite" && claim.kept === null && !dropped && (
          <Text size="xs" c="dimmed">
            GLM chose this as a sound bite{claim.speaker ? `, said by ${claim.speaker}` : ""}. Keep
            the claim to change the speaker or make it ordinary evidence.
          </Text>
        )}
        {claim.words_changed && !dropped && (
          <Alert color="yellow" p="xs">
            {isOwner
              ? "The words of this claim are no longer in the story. Remove it and mark the new words."
              : "The words of this proposal are no longer in the story. Drop it."}
          </Alert>
        )}
        {!dropped && (
          <Group gap="xs" wrap="nowrap" onClick={(event) => event.stopPropagation()}>
            <Select
              size="xs"
              w={130}
              aria-label="Kind of claim"
              data={EVIDENCE_KINDS.map((kind) => ({ value: kind.value, label: kind.label }))}
              value={claim.kind_hint}
              allowDeselect={false}
              disabled={busy}
              onChange={(value) => {
                const kind = EVIDENCE_KINDS.find((item) => item.value === value);
                if (kind && kind.value !== claim.kind_hint) {
                  onEdit({ kind_hint: kind.value });
                }
              }}
            />
            <TextInput
              size="xs"
              style={{ flex: 1 }}
              aria-label="Note for the research (for example: must be the SEC filing)"
              placeholder="Note for the research (optional)"
              maxLength={300}
              value={hint}
              disabled={busy}
              onChange={(event) => setHint(event.currentTarget.value)}
              onBlur={() => {
                if (hint !== claim.hint) {
                  onEdit({ hint });
                }
              }}
            />
          </Group>
        )}
        {!dropped && !claim.words_changed && claim.kept !== null && (
          <SoundbiteControls claim={claim} busy={busy} onEdit={onEdit} />
        )}
      </Stack>
    </Paper>
  );
}

type Props = {
  project: ProjectDetail;
  /** The story box holds changes that are not saved: the words shown here would not match. */
  hasUnsavedStory: boolean;
};

/**
 * The words of the saved story that need proof on screen (a figure, a price, something a person
 * said). Select words and mark them as a claim, with a note for the research. GLM can propose
 * more, which you keep or drop. The claims are what the research round works from.
 */
export function EvidenceClaims({ project, hasUnsavedStory }: Props) {
  const story = project.script_text;
  const { data, isLoading, isError, error } = useEvidenceClaims(project.id);
  const mark = useMarkEvidenceClaim(project.id);
  const edit = useEditEvidenceClaim(project.id);
  const remove = useRemoveEvidenceClaim(project.id);
  const suggest = useSuggestEvidenceClaims(project.id);

  const rootRef = useRef<HTMLDivElement>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [hint, setHint] = useState("");
  const [kind, setKind] = useState<string>(AUTOMATIC);
  const [activeId, setActiveId] = useState<string | null>(null);

  const claims = useMemo(() => data?.claims ?? [], [data]);
  const job = data?.job ?? null;
  const asking = isJobActive(job);
  const busy = asking || mark.isPending || edit.isPending || remove.isPending;

  const positions = useMemo(() => buildPositions(story ?? ""), [story]);
  const segments = useMemo(
    () => buildSegments(story ?? "", claims, positions),
    [story, claims, positions],
  );

  useEffect(() => {
    function onSelectionChange() {
      // Typing a note moves the selection into the field: keep the words that were selected.
      const focused = document.activeElement;
      if (focused instanceof HTMLInputElement || focused instanceof HTMLTextAreaElement) {
        return;
      }
      const root = rootRef.current;
      const selection = window.getSelection();
      if (!root || !selection || selection.rangeCount === 0 || selection.isCollapsed) {
        setPending(null);
        return;
      }
      const range = selection.getRangeAt(0);
      const length = (story ?? "").length;
      const from = unitOffset(root, range.startContainer, range.startOffset, length);
      const to = unitOffset(root, range.endContainer, range.endOffset, length);
      if (from === null || to === null || from >= to) {
        setPending(null);
        return;
      }
      const start = positions.toPoint[from];
      const end = positions.toPoint[to];
      const text = positions.points.slice(start, end).join("");
      setPending(text.trim() === "" ? null : { start, end, text });
    }
    document.addEventListener("selectionchange", onSelectionChange);
    return () => document.removeEventListener("selectionchange", onSelectionChange);
  }, [story, positions]);

  function markSelection() {
    if (!pending) {
      return;
    }
    const chosen = EVIDENCE_KINDS.find((item) => item.value === kind);
    mark.mutate(
      { ...pending, hint, kind_hint: chosen ? chosen.value : null },
      {
        onSuccess: () => {
          window.getSelection()?.removeAllRanges();
          setPending(null);
          setHint("");
          setKind(AUTOMATIC);
        },
      },
    );
  }

  const decided = claims.filter((claim) => claim.kept !== false);
  const droppedClaims = claims.filter((claim) => claim.kept === false);
  const undecided = claims.filter((claim) => claim.origin === "glm" && claim.kept === null).length;

  function card(claim: EvidenceClaim) {
    return (
      <ClaimCard
        key={claim.id}
        claim={claim}
        active={claim.id === activeId}
        busy={busy}
        onSelect={() => setActiveId(claim.id === activeId ? null : claim.id)}
        onEdit={(change) => edit.mutate({ claimId: claim.id, edit: change })}
        onRemove={() => remove.mutate(claim.id)}
      />
    );
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Title order={4}>Evidence claims</Title>
        <Text size="sm" c="dimmed">
          Select the words that need proof on screen (a price, a figure from a report, something a
          person or a company said), then click Mark as claim. GLM can propose more claims, and
          you keep or drop each one. Your own marks are always kept. The research works from this
          list. A quote written as whole sentences in quotation marks can be made a sound bite: a
          clip of the person saying it, which replaces the narrator&apos;s reading.
        </Text>
        {story === null ? (
          <Alert color="gray">Save the story first, then mark the claims here.</Alert>
        ) : hasUnsavedStory ? (
          <Alert color="yellow">
            The story has changes that are not saved. Save the story first, then mark the claims
            here.
          </Alert>
        ) : (
          <>
            <Paper withBorder p="sm" radius="sm" mah={360} style={{ overflowY: "auto" }}>
              <div
                ref={rootRef}
                aria-label="Story, to mark evidence claims"
                style={{ whiteSpace: "pre-wrap", fontSize: "var(--mantine-font-size-sm)" }}
              >
                {segments.map((segment) =>
                  segment.claim === null ? (
                    <span key={segment.start} data-start={segment.start}>
                      {segment.text}
                    </span>
                  ) : (
                    <mark
                      key={segment.start}
                      data-start={segment.start}
                      onClick={() => {
                        const id = segment.claim?.id ?? null;
                        setActiveId(id === activeId ? null : id);
                      }}
                      style={{
                        cursor: "pointer",
                        color: "inherit",
                        background: markBackground(segment.claim, segment.claim.id === activeId),
                      }}
                    >
                      {segment.text}
                    </mark>
                  ),
                )}
              </div>
            </Paper>
            <Group align="flex-end" gap="sm">
              <TextInput
                size="xs"
                style={{ flex: 1 }}
                label="Note for the research (optional)"
                placeholder="For example: must be the SEC filing"
                maxLength={300}
                value={hint}
                onChange={(event) => setHint(event.currentTarget.value)}
              />
              <Select
                size="xs"
                w={150}
                aria-label="Kind of claim"
                data={KIND_OPTIONS}
                value={kind}
                allowDeselect={false}
                onChange={(value) => setKind(value ?? AUTOMATIC)}
              />
              <Button
                // Keep the selection: pressing a button would otherwise clear it first.
                onMouseDown={(event) => event.preventDefault()}
                onClick={markSelection}
                disabled={pending === null || busy}
                loading={mark.isPending}
              >
                Mark as claim
              </Button>
            </Group>
            {pending && (
              <Text size="xs" c="dimmed" lineClamp={2}>
                Selected: {pending.text}
              </Text>
            )}
          </>
        )}

        <Group justify="space-between" align="center">
          <Text size="sm" fw={500}>
            {decided.length === 0
              ? "No claims yet"
              : `${decided.length} claim${decided.length === 1 ? "" : "s"}`}
            {undecided > 0 ? `, ${undecided} to decide` : ""}
          </Text>
          <Button
            variant="default"
            onClick={() => suggest.mutate()}
            loading={suggest.isPending || asking}
            disabled={
              isLoading || isError || story === null || hasUnsavedStory || data?.wanted === false
            }
          >
            {data?.has_ai_version ? "Ask GLM again" : "Ask GLM for more claims"}
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          Asking GLM is a paid call. It replaces only the proposals you have not decided on; the
          ones you kept or dropped stay.
        </Text>
        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the claims">
            {describeError(error)}
          </Alert>
        )}
        {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
        {job?.status === "failed" && (
          <Alert color="red" title="The last request to GLM failed">
            {job.error ?? "The job failed."}
          </Alert>
        )}
        {suggest.isError && (
          <Alert color="red" title="Could not ask GLM">
            {describeError(suggest.error)}
          </Alert>
        )}
        {mark.isError && (
          <Alert color="red" title="The claim was not marked">
            {describeError(mark.error)}
          </Alert>
        )}
        {edit.isError && (
          <Alert color="red" title="The claim was not changed">
            {describeError(edit.error)}
          </Alert>
        )}
        {remove.isError && (
          <Alert color="red" title="The claim was not removed">
            {describeError(remove.error)}
          </Alert>
        )}

        {decided.length > 0 && <Stack gap="xs">{decided.map(card)}</Stack>}
        {droppedClaims.length > 0 && (
          <Stack gap="xs">
            <Text size="sm" c="dimmed">
              Dropped proposals ({droppedClaims.length}). GLM will not propose these again.
            </Text>
            {droppedClaims.map(card)}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
