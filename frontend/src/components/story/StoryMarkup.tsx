import { useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Alert,
  Badge,
  Box,
  Button,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  Stack,
  Text,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useEditEvidenceClaim,
  useEvidenceClaims,
  useMarkEvidenceClaim,
  useRemoveEvidenceClaim,
  useSuggestEvidenceClaims,
  type EvidenceClaim,
} from "../../api/evidenceClaims";
import { isJobActive } from "../../api/polling";
import {
  useSetGraphicSuggestions,
  type GraphicSuggestion,
  type ProjectDetail,
} from "../../api/projects";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { EvidenceClaimCard } from "./EvidenceClaimCard";
import {
  SelectionToolbar,
  type EvidenceOptions,
  type MarkAction,
} from "./SelectionToolbar";
import {
  buildLayeredSegments,
  buildPositions,
  rangesOverlap,
  scrollToUnit,
  useStorySelection,
  type LayeredSegment,
} from "./storyMarks";

/** Words of the story, as the backend wants them: positions in code points and the text. */
type Range = { start: number; end: number; text: string };

/** The mark the reader has opened in the details pane. */
type Active = { kind: "claim" | "graphic"; id: string } | null;

type Filter = "all" | "evidence" | "graphics" | "decide";

const OVERLAPS_OWN_CLAIM = "These words overlap a claim you already marked.";

function claimColour(claim: EvidenceClaim): string {
  return claim.kept === null ? "blue" : "teal";
}

/** Whether the story shows the claim: a dropped proposal, or one whose words are gone, is not. */
function isShown(claim: EvidenceClaim): boolean {
  return claim.kept !== false && !claim.words_changed;
}

// --- The story with its marks ---------------------------------------------------------------

type StoryTextProps = {
  segments: LayeredSegment[];
  claims: Map<string, EvidenceClaim>;
  active: Active;
  onPick: (pick: NonNullable<Active>) => void;
};

function markStyle(
  segment: LayeredSegment,
  claim: EvidenceClaim | undefined,
  active: Active,
): CSSProperties {
  const style: CSSProperties = { cursor: "pointer", color: "inherit", background: "none" };
  if (claim) {
    const colour = claimColour(claim);
    style.background = `var(--mantine-color-${colour}-${claim.id === active?.id && active.kind === "claim" ? "filled" : "light"})`;
    if (claim.kept === null) {
      style.outline = "1px dashed var(--mantine-color-blue-filled)";
    }
  }
  if (segment.graphicId !== null) {
    style.textDecoration = "underline";
    style.textDecorationColor = "var(--mantine-color-yellow-filled)";
    style.textDecorationThickness = "3px";
    style.textUnderlineOffset = "3px";
  }
  if (
    active &&
    ((active.kind === "claim" && active.id === segment.claimId) ||
      (active.kind === "graphic" && active.id === segment.graphicId))
  ) {
    style.boxShadow = "0 0 0 2px var(--mantine-color-blue-filled)";
    style.borderRadius = "2px";
  }
  return style;
}

function StoryText({ segments, claims, active, onPick }: StoryTextProps) {
  return (
    <>
      {segments.map((segment) => {
        if (segment.claimId === null && segment.graphicId === null) {
          return (
            <span key={segment.start} data-start={segment.start}>
              {segment.text}
            </span>
          );
        }
        const claim = segment.claimId === null ? undefined : claims.get(segment.claimId);
        const labels = [claim ? "Evidence" : null, segment.graphicId ? "Graphic" : null];
        return (
          <mark
            key={segment.start}
            data-start={segment.start}
            title={labels.filter((label) => label !== null).join(" and ")}
            onClick={() => {
              // Letting go after selecting words is also a click: do not open a mark then.
              if (!window.getSelection()?.isCollapsed) {
                return;
              }
              if (segment.claimId !== null) {
                onPick({ kind: "claim", id: segment.claimId });
              } else if (segment.graphicId !== null) {
                onPick({ kind: "graphic", id: segment.graphicId });
              }
            }}
            style={markStyle(segment, claim, active)}
          >
            {segment.text}
          </mark>
        );
      })}
    </>
  );
}

function Legend({
  evidence,
  graphics,
  undecided,
  showEvidence,
  showGraphics,
}: {
  evidence: number;
  graphics: number;
  undecided: number;
  showEvidence: boolean;
  showGraphics: boolean;
}) {
  return (
    <Group gap="md">
      {showEvidence && (
        <Group gap={6}>
          <Box
            w={14}
            h={14}
            style={{
              borderRadius: 3,
              background: "var(--mantine-color-teal-light)",
              border: "1px solid var(--mantine-color-teal-filled)",
            }}
          />
          <Text size="xs">Evidence: {evidence}</Text>
        </Group>
      )}
      {showEvidence && undecided > 0 && (
        <Group gap={6}>
          <Box
            w={14}
            h={14}
            style={{
              borderRadius: 3,
              background: "var(--mantine-color-blue-light)",
              border: "1px dashed var(--mantine-color-blue-filled)",
            }}
          />
          <Text size="xs">GLM proposals to decide: {undecided}</Text>
        </Group>
      )}
      {showGraphics && (
        <Group gap={6}>
          <Box
            w={14}
            h={14}
            style={{ borderBottom: "3px solid var(--mantine-color-yellow-filled)" }}
          />
          <Text size="xs">Graphics: {graphics}</Text>
        </Group>
      )}
    </Group>
  );
}

// --- The list of marks ----------------------------------------------------------------------

type Entry = {
  key: string;
  pick: NonNullable<Active>;
  start: number;
  end: number;
  text: string;
  claim: EvidenceClaim | null;
};

function claimEntry(claim: EvidenceClaim): Entry {
  return {
    key: `claim-${claim.id}`,
    pick: { kind: "claim", id: claim.id },
    start: claim.start,
    end: claim.end,
    text: claim.text,
    claim,
  };
}

function graphicEntry(graphic: GraphicSuggestion): Entry {
  return {
    key: `graphic-${graphic.id}`,
    pick: { kind: "graphic", id: graphic.id },
    start: graphic.start,
    end: graphic.end,
    text: graphic.text,
    claim: null,
  };
}

function EntryRow({
  entry,
  busy,
  onOpen,
  onEdit,
}: {
  entry: Entry;
  busy: boolean;
  onOpen: () => void;
  onEdit: (claimId: string, kept: boolean) => void;
}) {
  const { claim } = entry;
  return (
    <Paper withBorder p="xs" radius="sm" style={{ cursor: "pointer" }} onClick={onOpen}>
      <Stack gap={4}>
        <Group gap={6} wrap="wrap">
          {claim ? (
            <>
              <Badge color={claimColour(claim)} variant="light">
                Evidence · {claim.origin === "owner" ? "You" : "GLM"}
              </Badge>
              {claim.origin === "glm" && claim.kept === null && (
                <Badge color="gray" variant="outline">
                  To decide
                </Badge>
              )}
              {claim.kept === false && (
                <Badge color="gray" variant="outline">
                  Dropped
                </Badge>
              )}
              {claim.want === "soundbite" && claim.kept !== false && (
                <Badge color="grape" variant="light">
                  Sound bite
                </Badge>
              )}
              {claim.words_changed && claim.kept !== false && (
                <Badge color="yellow" variant="light">
                  Words changed
                </Badge>
              )}
            </>
          ) : (
            <Badge color="yellow" variant="light">
              Graphic
            </Badge>
          )}
        </Group>
        <Text size="sm" lineClamp={2}>
          {entry.text}
        </Text>
        {claim && claim.origin === "glm" && claim.kept !== true && (
          <Group gap="xs" onClick={(event) => event.stopPropagation()}>
            <Button
              size="compact-xs"
              disabled={busy || claim.words_changed}
              onClick={() => onEdit(claim.id, true)}
            >
              {claim.kept === false ? "Keep again" : "Keep"}
            </Button>
            {claim.kept !== false && (
              <Button
                size="compact-xs"
                variant="default"
                disabled={busy}
                onClick={() => onEdit(claim.id, false)}
              >
                Drop
              </Button>
            )}
          </Group>
        )}
      </Stack>
    </Paper>
  );
}

// --- The view -------------------------------------------------------------------------------

type Props = {
  project: ProjectDetail;
  /** The story box holds changes that are not saved: the words shown here would not match. */
  hasUnsavedStory: boolean;
  /** Takes the reader back to the page where the story is written, when there is one. */
  onGoToWrite?: () => void;
};

/**
 * The saved story with every mark on it. Select words and choose Evidence (words that need
 * proof on screen), Graphic (words to draw as a chart, a diagram or a text card) or Both. Evidence
 * is a background, a graphic an underline. The pane beside the story lists the marks, and shows
 * the settings of the one that is open. GLM can propose more claims, which you keep or drop.
 */
export function StoryMarkup({ project, hasUnsavedStory, onGoToWrite }: Props) {
  const story = project.script_text;
  const canEvidence = project.voice_track === "continuous" && project.evidence;
  const canGraphic = project.voice_track === "continuous" && project.graphics;

  const claimsQuery = useEvidenceClaims(project.id, canEvidence);
  const mark = useMarkEvidenceClaim(project.id);
  const edit = useEditEvidenceClaim(project.id);
  const remove = useRemoveEvidenceClaim(project.id);
  const suggest = useSuggestEvidenceClaims(project.id);
  const saveGraphics = useSetGraphicSuggestions(project.id);

  const rootRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<Active>(null);
  const [filter, setFilter] = useState<Filter>("all");
  // Set when "Both" saved the evidence but not the graphic.
  const [partial, setPartial] = useState(false);
  const [marking, setMarking] = useState(false);

  const claims = useMemo(
    () => (canEvidence ? (claimsQuery.data?.claims ?? []) : []),
    [canEvidence, claimsQuery.data],
  );
  const graphics = useMemo(
    () => (canGraphic ? project.graphic_suggestions : []),
    [canGraphic, project.graphic_suggestions],
  );
  const job = claimsQuery.data?.job ?? null;
  const asking = isJobActive(job);
  const busy =
    asking ||
    marking ||
    mark.isPending ||
    edit.isPending ||
    remove.isPending ||
    saveGraphics.isPending;

  const positions = useMemo(() => buildPositions(story ?? ""), [story]);
  const shownClaims = useMemo(() => claims.filter(isShown), [claims]);
  const claimById = useMemo(() => new Map(claims.map((claim) => [claim.id, claim])), [claims]);
  const segments = useMemo(
    () => buildLayeredSegments(story ?? "", graphics, shownClaims, positions),
    [story, graphics, shownClaims, positions],
  );
  const { selection, clear } = useStorySelection(rootRef, story, positions);

  const ownClaims = shownClaims.filter((claim) => claim.origin === "owner");
  const evidenceBlockedReason =
    selection && ownClaims.some((claim) => rangesOverlap(selection, claim))
      ? OVERLAPS_OWN_CLAIM
      : null;

  const currentGraphics = graphics.map(({ start, end, text }) => ({ start, end, text }));

  function resetErrors() {
    mark.reset();
    edit.reset();
    remove.reset();
    saveGraphics.reset();
    setPartial(false);
  }

  /** Saves the evidence first (it is the one that can be refused), then the graphic. */
  async function runMark(action: MarkAction, range: Range, options: EvidenceOptions) {
    resetErrors();
    setMarking(true);
    let evidenceSaved = false;
    try {
      if (action !== "graphic") {
        await mark.mutateAsync({ ...range, hint: options.hint, kind_hint: options.kind });
        evidenceSaved = true;
      }
      if (action !== "evidence") {
        await saveGraphics.mutateAsync([...currentGraphics, range]);
      }
      clear();
    } catch {
      // The error is shown from the request that failed.
      if (evidenceSaved) {
        setPartial(true);
        clear();
      }
    } finally {
      setMarking(false);
    }
  }

  function removeGraphic(id: string) {
    resetErrors();
    saveGraphics.mutate(
      graphics
        .filter((graphic) => graphic.id !== id)
        .map(({ start, end, text }) => ({ start, end, text })),
    );
  }

  function changeClaim(claimId: string, change: Parameters<typeof edit.mutate>[0]["edit"]) {
    resetErrors();
    edit.mutate({ claimId, edit: change });
  }

  function removeClaim(claimId: string) {
    resetErrors();
    remove.mutate(claimId);
  }

  function openMark(pick: NonNullable<Active>, scroll: boolean) {
    setActive((current) =>
      !scroll && current?.kind === pick.kind && current.id === pick.id ? null : pick,
    );
    if (scroll) {
      const claim = pick.kind === "claim" ? claimById.get(pick.id) : undefined;
      const graphic = pick.kind === "graphic" ? graphics.find((g) => g.id === pick.id) : undefined;
      const point = claim && isShown(claim) ? claim.start : graphic?.start;
      if (point !== undefined) {
        scrollToUnit(rootRef.current, positions.toUnit[point]);
      }
    }
  }

  // --- What the details pane shows ---

  const activeClaim =
    active?.kind === "claim" ? (claimById.get(active.id) ?? null) : null;
  const activeGraphic =
    active?.kind === "graphic" ? (graphics.find((graphic) => graphic.id === active.id) ?? null) : null;
  const activeRange: Range | null = activeClaim
    ? activeClaim.words_changed
      ? null
      : { start: activeClaim.start, end: activeClaim.end, text: activeClaim.text }
    : activeGraphic
      ? { start: activeGraphic.start, end: activeGraphic.end, text: activeGraphic.text }
      : null;
  const claimsHere = activeClaim
    ? [activeClaim]
    : activeRange
      ? shownClaims.filter((claim) => rangesOverlap(claim, activeRange))
      : [];
  const graphicsHere = activeGraphic
    ? [activeGraphic]
    : activeRange
      ? graphics.filter((graphic) => rangesOverlap(graphic, activeRange))
      : [];
  const showDetails = activeClaim !== null || activeGraphic !== null;

  // --- The list ---

  const entries: Entry[] = [
    ...claims.filter((claim) => claim.kept !== false).map(claimEntry),
    ...graphics.map(graphicEntry),
  ].sort((a, b) => a.start - b.start || a.key.localeCompare(b.key));
  const dropped = claims.filter((claim) => claim.kept === false).map(claimEntry);
  const undecided = claims.filter((claim) => claim.origin === "glm" && claim.kept === null).length;
  const evidenceCount = claims.filter((claim) => claim.kept !== false).length;

  const visible = entries.filter((entry) => {
    if (filter === "evidence") {
      return entry.claim !== null;
    }
    if (filter === "graphics") {
      return entry.claim === null;
    }
    if (filter === "decide") {
      return entry.claim?.origin === "glm" && entry.claim.kept === null;
    }
    return true;
  });
  const showDropped = dropped.length > 0 && (filter === "all" || filter === "evidence");

  const filterOptions = [
    { value: "all", label: "All" },
    ...(canEvidence ? [{ value: "evidence", label: "Evidence" }] : []),
    ...(canGraphic ? [{ value: "graphics", label: "Graphics" }] : []),
    ...(canEvidence ? [{ value: "decide", label: `To decide${undecided > 0 ? ` (${undecided})` : ""}` }] : []),
  ];

  function row(entry: Entry) {
    return (
      <EntryRow
        key={entry.key}
        entry={entry}
        busy={busy}
        onOpen={() => openMark(entry.pick, true)}
        onEdit={(claimId, kept) => changeClaim(claimId, { kept })}
      />
    );
  }

  const intro =
    canEvidence && canGraphic
      ? "Select words, then choose Evidence (proof on screen), Graphic (a chart, a diagram or a text card) or Both in the bar that appears."
      : canEvidence
        ? "Select words that need proof on screen (a price, a figure, something a person said), then choose Evidence in the bar that appears."
        : "Select words that would work well as a graphic (a chart, a diagram or a text card), then choose Graphic in the bar that appears.";

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        {intro} Graphics are drawn over the shots under the words, which are not planned again.
        {canEvidence &&
          " A quote written as whole sentences in quotation marks can be made a sound bite: a clip of the person saying it."}
      </Text>
      {story === null ? (
        <Alert color="gray">
          Save the story first, then mark it up here.
          {onGoToWrite && (
            <Button mt="xs" size="compact-sm" variant="default" onClick={onGoToWrite} display="block">
              Go to Write
            </Button>
          )}
        </Alert>
      ) : hasUnsavedStory ? (
        <Alert color="yellow">
          The story has changes that are not saved. Save the story first, then mark it up here.
          {onGoToWrite && (
            <Button mt="xs" size="compact-sm" variant="default" onClick={onGoToWrite} display="block">
              Go to Write
            </Button>
          )}
        </Alert>
      ) : (
        <>
          <Group justify="space-between" align="center">
            <Legend
              evidence={evidenceCount}
              graphics={graphics.length}
              undecided={undecided}
              showEvidence={canEvidence}
              showGraphics={canGraphic}
            />
            {canEvidence && (
              <Group gap="xs">
                {claimsQuery.isLoading && <Loader size="xs" />}
                <Button
                  size="compact-sm"
                  variant="default"
                  onClick={() => suggest.mutate()}
                  loading={suggest.isPending || asking}
                  disabled={
                    claimsQuery.isLoading ||
                    claimsQuery.isError ||
                    claimsQuery.data?.wanted === false
                  }
                  title="A paid call. It replaces only the proposals you have not decided on."
                >
                  {claimsQuery.data?.has_ai_version ? "Ask GLM again" : "Ask GLM for more claims"}
                </Button>
              </Group>
            )}
          </Group>
          <Group align="flex-start" gap="md" wrap="wrap">
            <Paper
              withBorder
              p="sm"
              radius="sm"
              style={{ flex: "3 1 420px", minWidth: 0, maxHeight: 560, overflowY: "auto" }}
            >
              <div
                ref={rootRef}
                aria-label="Story, to mark evidence and graphics"
                style={{ whiteSpace: "pre-wrap", fontSize: "var(--mantine-font-size-sm)" }}
              >
                <StoryText
                  segments={segments}
                  claims={claimById}
                  active={active}
                  onPick={(pick) => openMark(pick, false)}
                />
              </div>
            </Paper>
            <Stack
              gap="xs"
              style={{ flex: "2 1 320px", minWidth: 0, maxHeight: 560, overflowY: "auto" }}
            >
              {showDetails ? (
                <>
                  <Group justify="space-between">
                    <Button size="compact-sm" variant="subtle" onClick={() => setActive(null)}>
                      All marks
                    </Button>
                  </Group>
                  {canEvidence && (
                    <Stack gap="xs">
                      <Text size="sm" fw={600}>
                        Evidence
                      </Text>
                      {claimsHere.length === 0 ? (
                        <Group gap="xs">
                          <Text size="sm" c="dimmed">
                            Not marked as evidence.
                          </Text>
                          {activeRange && (
                            <Button
                              size="compact-sm"
                              variant="default"
                              disabled={
                                busy ||
                                ownClaims.some((claim) => rangesOverlap(claim, activeRange))
                              }
                              onClick={() =>
                                void runMark("evidence", activeRange, { hint: "", kind: null })
                              }
                            >
                              Also mark as evidence
                            </Button>
                          )}
                        </Group>
                      ) : (
                        claimsHere.map((claim) => (
                          <EvidenceClaimCard
                            key={claim.id}
                            claim={claim}
                            busy={busy}
                            active={claim.id === activeClaim?.id}
                            onEdit={(change) => changeClaim(claim.id, change)}
                            onRemove={() => removeClaim(claim.id)}
                          />
                        ))
                      )}
                    </Stack>
                  )}
                  {canGraphic && (
                    <Stack gap="xs">
                      <Text size="sm" fw={600}>
                        Graphic
                      </Text>
                      {graphicsHere.length === 0 ? (
                        <Group gap="xs">
                          <Text size="sm" c="dimmed">
                            No graphic suggested.
                          </Text>
                          {activeRange && (
                            <Button
                              size="compact-sm"
                              variant="default"
                              disabled={busy}
                              onClick={() =>
                                void runMark("graphic", activeRange, { hint: "", kind: null })
                              }
                            >
                              Also suggest a graphic
                            </Button>
                          )}
                        </Group>
                      ) : (
                        graphicsHere.map((graphic) => (
                          <Paper key={graphic.id} withBorder p="sm" radius="sm">
                            <Group justify="space-between" wrap="nowrap" align="flex-start">
                              <Group gap="xs" wrap="nowrap" align="flex-start">
                                <Badge color="yellow" variant="light">
                                  Graphic
                                </Badge>
                                <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                                  {graphic.text}
                                </Text>
                              </Group>
                              <Button
                                size="compact-sm"
                                variant="default"
                                disabled={busy}
                                onClick={() => removeGraphic(graphic.id)}
                              >
                                Remove
                              </Button>
                            </Group>
                          </Paper>
                        ))
                      )}
                    </Stack>
                  )}
                </>
              ) : (
                <>
                  {filterOptions.length > 2 && (
                    <SegmentedControl
                      size="xs"
                      fullWidth
                      data={filterOptions}
                      value={filter}
                      onChange={(value) => setFilter(value as Filter)}
                    />
                  )}
                  {visible.length === 0 && !showDropped ? (
                    <Text size="sm" c="dimmed">
                      {entries.length === 0
                        ? "Nothing is marked yet. Select words in the story."
                        : "Nothing to show with this filter."}
                    </Text>
                  ) : (
                    <Stack gap="xs">{visible.map(row)}</Stack>
                  )}
                  {showDropped && (
                    <Stack gap="xs">
                      <Text size="xs" c="dimmed">
                        Dropped proposals ({dropped.length}). GLM will not propose these again.
                      </Text>
                      {dropped.map(row)}
                    </Stack>
                  )}
                </>
              )}
            </Stack>
          </Group>
        </>
      )}

      {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
      {job?.status === "failed" && (
        <Alert color="red" title="The last request to GLM failed">
          {job.error ?? "The job failed."}
        </Alert>
      )}
      {claimsQuery.isError && (
        <Alert color="red" title="Could not load the claims">
          {describeError(claimsQuery.error)}
        </Alert>
      )}
      {suggest.isError && (
        <Alert color="red" title="Could not ask GLM">
          {describeError(suggest.error)}
        </Alert>
      )}
      {partial && (
        <Alert color="yellow" title="Only the evidence was marked">
          The words are marked as evidence, but the graphic was not saved. Open the mark and use
          Also suggest a graphic to try again.
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
      {saveGraphics.isError && (
        <Alert color="red" title="The graphics were not saved">
          {describeError(saveGraphics.error)}
        </Alert>
      )}

      {selection && !hasUnsavedStory && (canEvidence || canGraphic) && (
        <SelectionToolbar
          key={`${selection.start}-${selection.end}`}
          selection={selection}
          canEvidence={canEvidence}
          canGraphic={canGraphic}
          evidenceBlockedReason={evidenceBlockedReason}
          busy={busy}
          onMark={(action, options) =>
            void runMark(
              action,
              { start: selection.start, end: selection.end, text: selection.text },
              options,
            )
          }
          onCancel={clear}
        />
      )}
    </Stack>
  );
}
