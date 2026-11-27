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
import {
  useEditFootageMark,
  useFootageMarks,
  useMarkFootage,
  useRemoveFootageMark,
  useSuggestFootageMarks,
  type FootageMark,
} from "../../api/footageMarks";
import { isJobActive } from "../../api/polling";
import {
  useSetGraphicSuggestions,
  type GraphicSuggestion,
  type ProjectDetail,
} from "../../api/projects";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { EvidenceClaimCard } from "./EvidenceClaimCard";
import { FootageMarkCard } from "./FootageMarkCard";
import {
  SelectionToolbar,
  type EvidenceOptions,
  type FootageOptions,
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
type Active = { kind: "claim" | "graphic" | "footage"; id: string } | null;

type Filter = "all" | "evidence" | "graphics" | "footage" | "decide";

const OVERLAPS_OWN_CLAIM = "These words overlap a claim you already marked.";
const OVERLAPS_OWN_FOOTAGE = "These words overlap footage you already marked.";

function claimColour(claim: EvidenceClaim): string {
  return claim.kept === null ? "blue" : "teal";
}

/**
 * Whether the story shows the mark (a claim or footage): a dropped proposal, or one whose words
 * are gone, is not.
 */
function isShown(mark: { kept: boolean | null; words_changed: boolean }): boolean {
  return mark.kept !== false && !mark.words_changed;
}

// --- The story with its marks ---------------------------------------------------------------

type StoryTextProps = {
  segments: LayeredSegment[];
  claims: Map<string, EvidenceClaim>;
  footage: Map<string, FootageMark>;
  active: Active;
  onPick: (pick: NonNullable<Active>) => void;
};

function markStyle(
  segment: LayeredSegment,
  claim: EvidenceClaim | undefined,
  footage: FootageMark | undefined,
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
  if (footage) {
    // A line above the words, so footage can sit on the same words as evidence and a graphic.
    style.borderTop = `3px ${footage.kept === null ? "dashed" : "solid"} var(--mantine-color-orange-filled)`;
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
      (active.kind === "graphic" && active.id === segment.graphicId) ||
      (active.kind === "footage" && active.id === segment.footageId))
  ) {
    style.boxShadow = "0 0 0 2px var(--mantine-color-blue-filled)";
    style.borderRadius = "2px";
  }
  return style;
}

function StoryText({ segments, claims, footage, active, onPick }: StoryTextProps) {
  return (
    <>
      {segments.map((segment) => {
        if (
          segment.claimId === null &&
          segment.graphicId === null &&
          segment.footageId === null
        ) {
          return (
            <span key={segment.start} data-start={segment.start}>
              {segment.text}
            </span>
          );
        }
        const claim = segment.claimId === null ? undefined : claims.get(segment.claimId);
        const footageMark = segment.footageId === null ? undefined : footage.get(segment.footageId);
        const labels = [
          claim ? "Evidence" : null,
          segment.graphicId ? "Graphic" : null,
          footageMark ? "Footage" : null,
        ];
        return (
          <mark
            key={segment.start}
            data-start={segment.start}
            title={labels.filter((label) => label !== null).join(", ")}
            onClick={() => {
              // Letting go after selecting words is also a click: do not open a mark then.
              if (!window.getSelection()?.isCollapsed) {
                return;
              }
              if (segment.claimId !== null) {
                onPick({ kind: "claim", id: segment.claimId });
              } else if (segment.graphicId !== null) {
                onPick({ kind: "graphic", id: segment.graphicId });
              } else if (segment.footageId !== null) {
                onPick({ kind: "footage", id: segment.footageId });
              }
            }}
            style={markStyle(segment, claim, footageMark, active)}
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
  footage,
  undecided,
  showEvidence,
  showGraphics,
  showFootage,
}: {
  evidence: number;
  graphics: number;
  footage: number;
  undecided: number;
  showEvidence: boolean;
  showGraphics: boolean;
  showFootage: boolean;
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
      {showFootage && (
        <Group gap={6}>
          <Box
            w={14}
            h={14}
            style={{ borderTop: "3px solid var(--mantine-color-orange-filled)" }}
          />
          <Text size="xs">Footage: {footage}</Text>
        </Group>
      )}
      {(showEvidence || showFootage) && undecided > 0 && (
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
  footage: FootageMark | null;
};

function claimEntry(claim: EvidenceClaim): Entry {
  return {
    key: `claim-${claim.id}`,
    pick: { kind: "claim", id: claim.id },
    start: claim.start,
    end: claim.end,
    text: claim.text,
    claim,
    footage: null,
  };
}

function footageEntry(footage: FootageMark): Entry {
  return {
    key: `footage-${footage.id}`,
    pick: { kind: "footage", id: footage.id },
    start: footage.start,
    end: footage.end,
    text: footage.text,
    claim: null,
    footage,
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
    footage: null,
  };
}

function EntryRow({
  entry,
  busy,
  onOpen,
  onEdit,
  onEditFootage,
}: {
  entry: Entry;
  busy: boolean;
  onOpen: () => void;
  onEdit: (claimId: string, kept: boolean) => void;
  onEditFootage: (markId: string, kept: boolean) => void;
}) {
  const { claim, footage } = entry;
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
          ) : footage ? (
            <>
              <Badge color={footage.kept === null ? "blue" : "orange"} variant="light">
                Footage · {footage.origin === "owner" ? "You" : "GLM"}
              </Badge>
              {footage.origin === "glm" && footage.kept === null && (
                <Badge color="gray" variant="outline">
                  To decide
                </Badge>
              )}
              {footage.kept === false && (
                <Badge color="gray" variant="outline">
                  Dropped
                </Badge>
              )}
              {footage.words_changed && footage.kept !== false && (
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
        {footage && footage.note !== "" && (
          <Text size="xs" c="dimmed" lineClamp={2}>
            {footage.note}
          </Text>
        )}
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
        {footage && footage.origin === "glm" && footage.kept !== true && (
          <Group gap="xs" onClick={(event) => event.stopPropagation()}>
            <Button
              size="compact-xs"
              disabled={busy || footage.words_changed}
              onClick={() => onEditFootage(footage.id, true)}
            >
              {footage.kept === false ? "Keep again" : "Keep"}
            </Button>
            {footage.kept !== false && (
              <Button
                size="compact-xs"
                variant="default"
                disabled={busy}
                onClick={() => onEditFootage(footage.id, false)}
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
 * proof on screen), Graphic (words to draw as a chart, a diagram or a text card), Both, or
 * Footage (words that real footage is shown over). Evidence is a background, a graphic an
 * underline and footage a line above the words. The pane beside the story lists the marks, and
 * shows the settings of the one that is open. GLM can propose more claims and more footage,
 * which you keep or drop.
 */
export function StoryMarkup({ project, hasUnsavedStory, onGoToWrite }: Props) {
  const story = project.script_text;
  const canEvidence = project.voice_track === "continuous" && project.evidence;
  const canGraphic = project.voice_track === "continuous" && project.graphics;
  const canFootage = project.voice_track === "continuous" && project.footage;

  const claimsQuery = useEvidenceClaims(project.id, canEvidence);
  const mark = useMarkEvidenceClaim(project.id);
  const edit = useEditEvidenceClaim(project.id);
  const remove = useRemoveEvidenceClaim(project.id);
  const suggest = useSuggestEvidenceClaims(project.id);
  const saveGraphics = useSetGraphicSuggestions(project.id);
  const footageQuery = useFootageMarks(project.id, canFootage);
  const markFootage = useMarkFootage(project.id);
  const editFootage = useEditFootageMark(project.id);
  const removeFootage = useRemoveFootageMark(project.id);
  const suggestFootage = useSuggestFootageMarks(project.id);

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
  const footage = useMemo(
    () => (canFootage ? (footageQuery.data?.marks ?? []) : []),
    [canFootage, footageQuery.data],
  );
  const job = claimsQuery.data?.job ?? null;
  const asking = isJobActive(job);
  const footageJob = footageQuery.data?.job ?? null;
  const askingFootage = isJobActive(footageJob);
  const busy =
    asking ||
    askingFootage ||
    marking ||
    mark.isPending ||
    edit.isPending ||
    remove.isPending ||
    saveGraphics.isPending ||
    markFootage.isPending ||
    editFootage.isPending ||
    removeFootage.isPending;

  const positions = useMemo(() => buildPositions(story ?? ""), [story]);
  const shownClaims = useMemo(() => claims.filter(isShown), [claims]);
  const claimById = useMemo(() => new Map(claims.map((claim) => [claim.id, claim])), [claims]);
  const shownFootage = useMemo(() => footage.filter(isShown), [footage]);
  const footageById = useMemo(() => new Map(footage.map((item) => [item.id, item])), [footage]);
  const segments = useMemo(
    () => buildLayeredSegments(story ?? "", graphics, shownClaims, shownFootage, positions),
    [story, graphics, shownClaims, shownFootage, positions],
  );
  const { selection, clear } = useStorySelection(rootRef, story, positions);

  const ownClaims = shownClaims.filter((claim) => claim.origin === "owner");
  const evidenceBlockedReason =
    selection && ownClaims.some((claim) => rangesOverlap(selection, claim))
      ? OVERLAPS_OWN_CLAIM
      : null;
  const ownFootage = shownFootage.filter((item) => item.origin === "owner");
  const footageBlockedReason =
    selection && ownFootage.some((item) => rangesOverlap(selection, item))
      ? OVERLAPS_OWN_FOOTAGE
      : null;

  const currentGraphics = graphics.map(({ start, end, text }) => ({ start, end, text }));

  function resetErrors() {
    mark.reset();
    edit.reset();
    remove.reset();
    saveGraphics.reset();
    markFootage.reset();
    editFootage.reset();
    removeFootage.reset();
    suggestFootage.reset();
    setPartial(false);
  }

  /**
   * Saves the evidence first (it is the one that can be refused), then the graphic. Footage is
   * marked alone, with its own note and kind.
   */
  async function runMark(
    action: MarkAction,
    range: Range,
    options: EvidenceOptions,
    footageOptions: FootageOptions = { note: "", kind: "any" },
  ) {
    resetErrors();
    setMarking(true);
    let evidenceSaved = false;
    try {
      if (action === "footage") {
        await markFootage.mutateAsync({
          ...range,
          note: footageOptions.note,
          kind_hint: footageOptions.kind,
        });
        clear();
        return;
      }
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

  function changeFootage(markId: string, change: Parameters<typeof editFootage.mutate>[0]["edit"]) {
    resetErrors();
    editFootage.mutate({ markId, edit: change });
  }

  function removeFootageMark(markId: string) {
    resetErrors();
    removeFootage.mutate(markId);
  }

  function openMark(pick: NonNullable<Active>, scroll: boolean) {
    setActive((current) =>
      !scroll && current?.kind === pick.kind && current.id === pick.id ? null : pick,
    );
    if (scroll) {
      const claim = pick.kind === "claim" ? claimById.get(pick.id) : undefined;
      const graphic = pick.kind === "graphic" ? graphics.find((g) => g.id === pick.id) : undefined;
      const footageMark = pick.kind === "footage" ? footageById.get(pick.id) : undefined;
      const point =
        claim && isShown(claim)
          ? claim.start
          : footageMark && isShown(footageMark)
            ? footageMark.start
            : graphic?.start;
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
  const activeFootage =
    active?.kind === "footage" ? (footageById.get(active.id) ?? null) : null;
  const activeRange: Range | null = activeClaim
    ? activeClaim.words_changed
      ? null
      : { start: activeClaim.start, end: activeClaim.end, text: activeClaim.text }
    : activeFootage
      ? activeFootage.words_changed
        ? null
        : { start: activeFootage.start, end: activeFootage.end, text: activeFootage.text }
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
  const footageHere = activeFootage
    ? [activeFootage]
    : activeRange
      ? shownFootage.filter((item) => rangesOverlap(item, activeRange))
      : [];
  const showDetails = activeClaim !== null || activeGraphic !== null || activeFootage !== null;

  // --- The list ---

  const entries: Entry[] = [
    ...claims.filter((claim) => claim.kept !== false).map(claimEntry),
    ...footage.filter((item) => item.kept !== false).map(footageEntry),
    ...graphics.map(graphicEntry),
  ].sort((a, b) => a.start - b.start || a.key.localeCompare(b.key));
  const dropped = [
    ...claims.filter((claim) => claim.kept === false).map(claimEntry),
    ...footage.filter((item) => item.kept === false).map(footageEntry),
  ].sort((a, b) => a.start - b.start || a.key.localeCompare(b.key));
  const undecidedClaims = claims.filter(
    (claim) => claim.origin === "glm" && claim.kept === null,
  ).length;
  const undecidedFootage = footage.filter(
    (item) => item.origin === "glm" && item.kept === null,
  ).length;
  const undecided = undecidedClaims + undecidedFootage;
  const evidenceCount = claims.filter((claim) => claim.kept !== false).length;
  const footageCount = footage.filter((item) => item.kept !== false).length;

  const visible = entries.filter((entry) => {
    if (filter === "evidence") {
      return entry.pick.kind === "claim";
    }
    if (filter === "graphics") {
      return entry.pick.kind === "graphic";
    }
    if (filter === "footage") {
      return entry.pick.kind === "footage";
    }
    if (filter === "decide") {
      return (
        (entry.claim?.origin === "glm" && entry.claim.kept === null) ||
        (entry.footage?.origin === "glm" && entry.footage.kept === null)
      );
    }
    return true;
  });
  const shownDropped = dropped.filter(
    (entry) =>
      filter === "all" ||
      (filter === "evidence" && entry.pick.kind === "claim") ||
      (filter === "footage" && entry.pick.kind === "footage"),
  );
  const showDropped = shownDropped.length > 0;

  const filterOptions = [
    { value: "all", label: "All" },
    ...(canEvidence ? [{ value: "evidence", label: "Evidence" }] : []),
    ...(canGraphic ? [{ value: "graphics", label: "Graphics" }] : []),
    ...(canFootage ? [{ value: "footage", label: "Footage" }] : []),
    ...(canEvidence || canFootage
      ? [{ value: "decide", label: `To decide${undecided > 0 ? ` (${undecided})` : ""}` }]
      : []),
  ];

  function row(entry: Entry) {
    return (
      <EntryRow
        key={entry.key}
        entry={entry}
        busy={busy}
        onOpen={() => openMark(entry.pick, true)}
        onEdit={(claimId, kept) => changeClaim(claimId, { kept })}
        onEditFootage={(markId, kept) => changeFootage(markId, { kept })}
      />
    );
  }

  const intro =
    canEvidence && canGraphic
      ? "Select words, then choose Evidence (proof on screen), Graphic (a chart, a diagram or a text card) or Both in the bar that appears."
      : canEvidence
        ? "Select words that need proof on screen (a price, a figure, something a person said), then choose Evidence in the bar that appears."
        : canGraphic
          ? "Select words that would work well as a graphic (a chart, a diagram or a text card), then choose Graphic in the bar that appears."
          : "Select words that real footage can be shown over (an event, a place, a person, a product), then choose Footage in the bar that appears.";

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        {intro}
        {(canEvidence || canGraphic) &&
          " Graphics are drawn over the shots under the words, which are not planned again."}
        {canEvidence &&
          " A quote written as whole sentences in quotation marks can be made a sound bite: a clip of the person saying it."}
        {canFootage &&
          (canEvidence || canGraphic
            ? " Choose Footage (key F) to show real footage over words, with a note on what the viewer should see."
            : " Footage is shown over the shots under the words while the narrator keeps talking, with a note on what the viewer should see.")}
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
              footage={footageCount}
              undecided={undecided}
              showEvidence={canEvidence}
              showGraphics={canGraphic}
              showFootage={canFootage}
            />
            <Group gap="xs">
              {canEvidence && (
                <>
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
                </>
              )}
              {canFootage && (
                <>
                  {footageQuery.isLoading && <Loader size="xs" />}
                  <Button
                    size="compact-sm"
                    variant="default"
                    onClick={() => suggestFootage.mutate()}
                    loading={suggestFootage.isPending || askingFootage}
                    disabled={
                      footageQuery.isLoading ||
                      footageQuery.isError ||
                      footageQuery.data?.wanted === false
                    }
                    title="A paid call. It replaces only the proposals you have not decided on."
                  >
                    {footageQuery.data?.has_ai_version
                      ? "Ask GLM again for footage"
                      : "Ask GLM for footage"}
                  </Button>
                </>
              )}
            </Group>
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
                aria-label="Story, to mark evidence, graphics and footage"
                style={{ whiteSpace: "pre-wrap", fontSize: "var(--mantine-font-size-sm)" }}
              >
                <StoryText
                  segments={segments}
                  claims={claimById}
                  footage={footageById}
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
                  {canFootage && (
                    <Stack gap="xs">
                      <Text size="sm" fw={600}>
                        Footage
                      </Text>
                      {footageHere.length === 0 ? (
                        <Group gap="xs">
                          <Text size="sm" c="dimmed">
                            Not marked as footage.
                          </Text>
                          {activeRange && (
                            <Button
                              size="compact-sm"
                              variant="default"
                              disabled={
                                busy ||
                                ownFootage.some((item) => rangesOverlap(item, activeRange))
                              }
                              onClick={() =>
                                void runMark(
                                  "footage",
                                  activeRange,
                                  { hint: "", kind: null },
                                  { note: "", kind: "any" },
                                )
                              }
                            >
                              Also mark as footage
                            </Button>
                          )}
                        </Group>
                      ) : (
                        footageHere.map((item) => (
                          <FootageMarkCard
                            key={item.id}
                            mark={item}
                            busy={busy}
                            active={item.id === activeFootage?.id}
                            onEdit={(change) => changeFootage(item.id, change)}
                            onRemove={() => removeFootageMark(item.id)}
                          />
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
                        Dropped proposals ({shownDropped.length}). GLM will not propose these again.
                      </Text>
                      {shownDropped.map(row)}
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
      {footageJob && footageJob.status !== "succeeded" && <JobStatusBadge job={footageJob} />}
      {footageJob?.status === "failed" && (
        <Alert color="red" title="The last request to GLM for footage failed">
          {footageJob.error ?? "The job failed."}
        </Alert>
      )}
      {footageQuery.isError && (
        <Alert color="red" title="Could not load the footage marks">
          {describeError(footageQuery.error)}
        </Alert>
      )}
      {suggestFootage.isError && (
        <Alert color="red" title="Could not ask GLM for footage">
          {describeError(suggestFootage.error)}
        </Alert>
      )}
      {markFootage.isError && (
        <Alert color="red" title="The footage was not marked">
          {describeError(markFootage.error)}
        </Alert>
      )}
      {editFootage.isError && (
        <Alert color="red" title="The footage mark was not changed">
          {describeError(editFootage.error)}
        </Alert>
      )}
      {removeFootage.isError && (
        <Alert color="red" title="The footage mark was not removed">
          {describeError(removeFootage.error)}
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

      {selection && !hasUnsavedStory && (canEvidence || canGraphic || canFootage) && (
        <SelectionToolbar
          key={`${selection.start}-${selection.end}`}
          selection={selection}
          canEvidence={canEvidence}
          canGraphic={canGraphic}
          canFootage={canFootage}
          evidenceBlockedReason={evidenceBlockedReason}
          footageBlockedReason={footageBlockedReason}
          busy={busy}
          onMark={(action, options, footageOptions) =>
            void runMark(
              action,
              { start: selection.start, end: selection.end, text: selection.text },
              options,
              footageOptions,
            )
          }
          onCancel={clear}
        />
      )}
    </Stack>
  );
}
