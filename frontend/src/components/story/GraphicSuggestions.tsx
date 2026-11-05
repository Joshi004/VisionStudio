import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Group, Paper, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useSetGraphicSuggestions,
  type GraphicSuggestion,
  type ProjectDetail,
} from "../../api/projects";

/**
 * The story's positions are in code points, as the backend counts them. The browser counts
 * UTF-16 units, which differ for a character such as an emoji. `toUnit[p]` is the unit position
 * of code point `p`, and `toPoint[u]` the code point of unit position `u`.
 */
type Positions = { points: string[]; toUnit: number[]; toPoint: number[] };

function buildPositions(text: string): Positions {
  const points = Array.from(text);
  const toUnit: number[] = [];
  const toPoint: number[] = new Array<number>(text.length + 1);
  let unit = 0;
  for (const point of points) {
    toPoint[unit] = toUnit.length;
    if (point.length === 2) {
      // The second half of a pair belongs to the same point.
      toPoint[unit + 1] = toUnit.length;
    }
    toUnit.push(unit);
    unit += point.length;
  }
  toUnit.push(unit);
  toPoint[unit] = points.length;
  return { points, toUnit, toPoint };
}

/** A part of the story: plain, or marked as a suggested graphic. `start` is a unit position. */
type Segment = { start: number; text: string; suggestionId: string | null };

function buildSegments(
  text: string,
  suggestions: GraphicSuggestion[],
  positions: Positions,
): Segment[] {
  const segments: Segment[] = [];
  let cursor = 0;
  const ordered = [...suggestions].sort((a, b) => a.start - b.start);
  for (const suggestion of ordered) {
    const start = positions.toUnit[suggestion.start];
    const end = positions.toUnit[suggestion.end];
    if (start === undefined || end === undefined || start < cursor || end <= start) {
      continue;
    }
    if (start > cursor) {
      segments.push({ start: cursor, text: text.slice(cursor, start), suggestionId: null });
    }
    segments.push({ start, text: text.slice(start, end), suggestionId: suggestion.id });
    cursor = end;
  }
  if (cursor < text.length) {
    segments.push({ start: cursor, text: text.slice(cursor), suggestionId: null });
  }
  return segments;
}

/**
 * The unit position in the story that a point of the browser's selection stands for, or null
 * when it is outside the story's text. Every segment is a direct child of `root` with the unit
 * position it starts at in `data-start`, and holds one text node.
 */
function unitOffset(root: HTMLElement, node: Node, offset: number, textLength: number) {
  if (!root.contains(node)) {
    return null;
  }
  if (node === root) {
    const child = root.children[offset];
    return child instanceof HTMLElement ? Number(child.dataset.start) : textLength;
  }
  let segment: Node | null = node;
  while (segment !== null && segment.parentNode !== root) {
    segment = segment.parentNode;
  }
  if (!(segment instanceof HTMLElement)) {
    return null;
  }
  const start = Number(segment.dataset.start);
  if (node.nodeType === Node.TEXT_NODE) {
    return start + offset;
  }
  return offset === 0 ? start : start + (segment.textContent?.length ?? 0);
}

type Pending = { start: number; end: number; text: string };

type Props = {
  project: ProjectDetail;
  /** The story box holds changes that are not saved: the words shown here would not match. */
  hasUnsavedStory: boolean;
};

/**
 * Words of the saved story the owner would like to see as a graphic. The shot planner takes
 * them as a hint: it follows one unless a rule or the words make it impossible, and says why
 * when it does not.
 */
export function GraphicSuggestions({ project, hasUnsavedStory }: Props) {
  const story = project.script_text;
  const suggestions = project.graphic_suggestions;
  const save = useSetGraphicSuggestions(project.id);
  const rootRef = useRef<HTMLDivElement>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);

  const positions = useMemo(() => buildPositions(story ?? ""), [story]);
  const segments = useMemo(
    () => buildSegments(story ?? "", suggestions, positions),
    [story, suggestions, positions],
  );

  useEffect(() => {
    function onSelectionChange() {
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

  const current = suggestions.map(({ start, end, text }) => ({ start, end, text }));
  const active = suggestions.find((suggestion) => suggestion.id === activeId) ?? null;

  function addSelection() {
    if (!pending) {
      return;
    }
    save.mutate([...current, pending], {
      onSuccess: () => {
        window.getSelection()?.removeAllRanges();
        setPending(null);
        setActiveId(null);
      },
    });
  }

  function removeActive() {
    if (!active) {
      return;
    }
    save.mutate(
      suggestions
        .filter((suggestion) => suggestion.id !== active.id)
        .map(({ start, end, text }) => ({ start, end, text })),
      { onSuccess: () => setActiveId(null) },
    );
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Title order={4}>Suggest graphics</Title>
        <Text size="sm" c="dimmed">
          Select the words that would work well as a graphic (a chart, a diagram or a text card),
          then click Suggest graphic. The shot planner follows a suggestion unless a rule or the
          words make it impossible, and gives its reason when it does not. A changed suggestion
          marks the shot plan of its scene as out of date.
        </Text>
        {story === null ? (
          <Alert color="gray">Save the story first, then mark the words here.</Alert>
        ) : hasUnsavedStory ? (
          <Alert color="yellow">
            The story has changes that are not saved. Save the story first, then mark the words
            here.
          </Alert>
        ) : (
          <>
            <Paper withBorder p="sm" radius="sm" mah={360} style={{ overflowY: "auto" }}>
              <div
                ref={rootRef}
                aria-label="Story, to mark graphic suggestions"
                style={{ whiteSpace: "pre-wrap", fontSize: "var(--mantine-font-size-sm)" }}
              >
                {segments.map((segment) =>
                  segment.suggestionId === null ? (
                    <span key={segment.start} data-start={segment.start}>
                      {segment.text}
                    </span>
                  ) : (
                    <mark
                      key={segment.start}
                      data-start={segment.start}
                      onClick={() =>
                        setActiveId(segment.suggestionId === activeId ? null : segment.suggestionId)
                      }
                      style={{
                        cursor: "pointer",
                        color: "inherit",
                        background:
                          segment.suggestionId === activeId
                            ? "var(--mantine-color-yellow-filled)"
                            : "var(--mantine-color-yellow-light)",
                      }}
                    >
                      {segment.text}
                    </mark>
                  ),
                )}
              </div>
            </Paper>
            <Group justify="space-between">
              <Group gap="sm">
                <Button
                  // Keep the selection: pressing a button would otherwise clear it first.
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={addSelection}
                  disabled={pending === null}
                  loading={save.isPending}
                >
                  Suggest graphic
                </Button>
                {active && (
                  <Button
                    variant="default"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={removeActive}
                    loading={save.isPending}
                  >
                    Remove selected suggestion
                  </Button>
                )}
              </Group>
              <Text size="xs" c="dimmed">
                {suggestions.length === 0
                  ? "No suggestions yet. Click a marked passage to select it for removal."
                  : `${suggestions.length} suggested. Click a marked passage to select it for removal.`}
              </Text>
            </Group>
          </>
        )}
        {save.isError && (
          <Alert color="red" title="The suggestions were not saved">
            {describeError(save.error)}
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}
