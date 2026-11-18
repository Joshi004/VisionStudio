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
