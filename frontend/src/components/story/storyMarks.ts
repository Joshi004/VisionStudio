import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

/**
 * Helpers for marking words of the story in the browser, shared by the graphic suggestions and
 * the evidence claims.
 *
 * The story's positions are in code points, as the backend counts them. The browser counts
 * UTF-16 units, which differ for a character such as an emoji. `toUnit[p]` is the unit position
 * of code point `p`, and `toPoint[u]` the code point of unit position `u`.
 */
export type Positions = { points: string[]; toUnit: number[]; toPoint: number[] };

export function buildPositions(text: string): Positions {
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

/**
 * The unit position in the story that a point of the browser's selection stands for, or null
 * when it is outside the story's text. Every segment is a direct child of `root` with the unit
 * position it starts at in `data-start`, and holds one text node.
 */
export function unitOffset(root: HTMLElement, node: Node, offset: number, textLength: number) {
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

// --- Whole words ---------------------------------------------------------------------------

const SPACE = /\s/u;

/**
 * The range of code points moved out to whole words, the same rule as the backend's
 * `snap_to_words`: it never begins or ends in the middle of a word, and spaces at its ends are
 * left out. Returns an empty range when it holds only spaces.
 */
export function snapToWords(points: string[], start: number, end: number): [number, number] {
  let from = start;
  let to = end;
  while (from < to && SPACE.test(points[from])) {
    from += 1;
  }
  while (to > from && SPACE.test(points[to - 1])) {
    to -= 1;
  }
  if (from === to) {
    return [from, to];
  }
  while (from > 0 && !SPACE.test(points[from - 1])) {
    from -= 1;
  }
  while (to < points.length && !SPACE.test(points[to])) {
    to += 1;
  }
  return [from, to];
}

/** Whether two ranges (the end not included) share at least one position. */
export function rangesOverlap(
  first: { start: number; end: number },
  second: { start: number; end: number },
): boolean {
  return first.start < second.end && first.end > second.start;
}

// --- The story cut into pieces -------------------------------------------------------------

/** A range of the story, in code points, that has an id (a claim or a suggested graphic). */
export type MarkRange = { id: string; start: number; end: number };

/**
 * A piece of the story with the same marks on all of it. `start` is a unit position. A piece
 * has at most one claim and one graphic; a piece with neither is plain text.
 */
export type LayeredSegment = {
  start: number;
  text: string;
  claimId: string | null;
  graphicId: string | null;
};

type UnitRange = { id: string; start: number; end: number };

function toUnitRanges(ranges: MarkRange[], positions: Positions): UnitRange[] {
  const result: UnitRange[] = [];
  for (const range of ranges) {
    const start = positions.toUnit[range.start];
    const end = positions.toUnit[range.end];
    if (start !== undefined && end !== undefined && end > start) {
      result.push({ id: range.id, start, end });
    }
  }
  return result;
}

function idAt(ranges: UnitRange[], from: number, to: number): string | null {
  const found = ranges.find((range) => range.start <= from && to <= range.end);
  return found ? found.id : null;
}

/**
 * The story cut at every start and end of a claim and of a graphic, so words that carry both
 * marks are one piece with both. Neighbouring pieces with the same marks are joined.
 */
export function buildLayeredSegments(
  text: string,
  graphics: MarkRange[],
  claims: MarkRange[],
  positions: Positions,
): LayeredSegment[] {
  const graphicRanges = toUnitRanges(graphics, positions);
  const claimRanges = toUnitRanges(claims, positions);
  const cuts = new Set<number>([0, text.length]);
  for (const range of [...graphicRanges, ...claimRanges]) {
    cuts.add(range.start);
    cuts.add(range.end);
  }
  const ordered = [...cuts].filter((cut) => cut >= 0 && cut <= text.length).sort((a, b) => a - b);

  const segments: LayeredSegment[] = [];
  for (let index = 0; index + 1 < ordered.length; index += 1) {
    const from = ordered[index];
    const to = ordered[index + 1];
    const claimId = idAt(claimRanges, from, to);
    const graphicId = idAt(graphicRanges, from, to);
    const last = segments[segments.length - 1];
    if (last && last.claimId === claimId && last.graphicId === graphicId) {
      last.text += text.slice(from, to);
    } else {
      segments.push({ start: from, text: text.slice(from, to), claimId, graphicId });
    }
  }
  return segments;
}

// --- The browser's selection ---------------------------------------------------------------

/** The words selected in the story, as they will be saved, and where they are on screen. */
export type StorySelection = {
  /** Code points, snapped to whole words. */
  start: number;
  end: number;
  text: string;
  /** Viewport coordinates of the selected words. */
  rect: { top: number; left: number; width: number; height: number };
};

function isTypingField(element: Element | null): boolean {
  return (
    element instanceof HTMLInputElement ||
    element instanceof HTMLTextAreaElement ||
    element instanceof HTMLSelectElement
  );
}

function toRect(range: Range) {
  const box = range.getBoundingClientRect();
  return { top: box.top, left: box.left, width: box.width, height: box.height };
}

/** The text node and offset of a unit position of the story, inside the segments of `root`. */
function domPoint(root: HTMLElement, unit: number): [Node, number] | null {
  for (const child of Array.from(root.children)) {
    if (!(child instanceof HTMLElement) || !child.firstChild) {
      continue;
    }
    const start = Number(child.dataset.start);
    const length = child.textContent?.length ?? 0;
    if (unit >= start && unit <= start + length) {
      return [child.firstChild, unit - start];
    }
  }
  return null;
}

/** Scrolls the piece of the story that starts at the unit position into view. */
export function scrollToUnit(root: HTMLElement | null, unit: number) {
  if (!root) {
    return;
  }
  for (const child of Array.from(root.children)) {
    if (child instanceof HTMLElement && Number(child.dataset.start) <= unit) {
      const length = child.textContent?.length ?? 0;
      if (unit < Number(child.dataset.start) + length) {
        child.scrollIntoView({ block: "center", behavior: "smooth" });
        return;
      }
    }
  }
}

/**
 * The words the reader has selected inside `rootRef`, grown out to whole words (the browser's
 * selection is changed to match, once the mouse or key is released, so what is highlighted is
 * what will be saved). It is null when nothing is selected there. Selecting inside a field,
 * such as the note box of the toolbar, keeps the last selection.
 */
export function useStorySelection(
  rootRef: RefObject<HTMLDivElement | null>,
  story: string | null,
  positions: Positions,
) {
  const [selection, setSelection] = useState<StorySelection | null>(null);
  const rangeRef = useRef<Range | null>(null);

  const clear = useCallback(() => {
    window.getSelection()?.removeAllRanges();
    rangeRef.current = null;
    setSelection(null);
  }, []);

  useEffect(() => {
    const length = (story ?? "").length;

    /** The selected words as code points (not yet snapped), and the range they come from. */
    function readSelection() {
      const root = rootRef.current;
      const live = window.getSelection();
      if (!root || !live || live.rangeCount === 0 || live.isCollapsed) {
        return null;
      }
      const range = live.getRangeAt(0);
      const from = unitOffset(root, range.startContainer, range.startOffset, length);
      const to = unitOffset(root, range.endContainer, range.endOffset, length);
      if (from === null || to === null || from >= to) {
        return null;
      }
      return { range, start: positions.toPoint[from], end: positions.toPoint[to] };
    }

    function onSelectionChange() {
      // Typing a note moves the selection into the field: keep the words that were selected.
      if (isTypingField(document.activeElement)) {
        return;
      }
      const read = readSelection();
      if (!read) {
        rangeRef.current = null;
        setSelection(null);
        return;
      }
      const [start, end] = snapToWords(positions.points, read.start, read.end);
      if (start >= end) {
        rangeRef.current = null;
        setSelection(null);
        return;
      }
      rangeRef.current = read.range.cloneRange();
      setSelection({
        start,
        end,
        text: positions.points.slice(start, end).join(""),
        rect: toRect(read.range),
      });
    }

    /** When the selection is released: make the browser's highlight cover whole words. */
    function onRelease() {
      const root = rootRef.current;
      if (!root || isTypingField(document.activeElement)) {
        return;
      }
      const read = readSelection();
      if (!read) {
        return;
      }
      const [start, end] = snapToWords(positions.points, read.start, read.end);
      if (start >= end || (start === read.start && end === read.end)) {
        return;
      }
      const from = domPoint(root, positions.toUnit[start]);
      const to = domPoint(root, positions.toUnit[end]);
      const live = window.getSelection();
      if (!from || !to || !live) {
        return;
      }
      const range = document.createRange();
      range.setStart(from[0], from[1]);
      range.setEnd(to[0], to[1]);
      live.removeAllRanges();
      live.addRange(range);
    }

    /** The page moved: place the toolbar again from the range that was selected. */
    function onScroll() {
      const range = rangeRef.current;
      if (!range) {
        return;
      }
      const rect = toRect(range);
      setSelection((current) => (current ? { ...current, rect } : current));
    }

    document.addEventListener("selectionchange", onSelectionChange);
    document.addEventListener("pointerup", onRelease);
    document.addEventListener("keyup", onRelease);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      document.removeEventListener("selectionchange", onSelectionChange);
      document.removeEventListener("pointerup", onRelease);
      document.removeEventListener("keyup", onRelease);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [rootRef, story, positions]);

  return { selection, clear };
}
