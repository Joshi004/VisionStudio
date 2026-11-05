// Fitting text into the space of a block (§4.5.2, "Text fit in the browser"). The browser measures
// each text in the font's own file (`measureText` of the templates), so what the layout reports is
// what is drawn. A text is never cut and never made smaller than 1 px here: a text that had to
// become small is left small, and the layout check of the backend lists it (under 2 percent of
// the height) so the model can be asked once to fix it.
import type { Box } from "../types";
import { FIT_SHARE, LINE_HEIGHT, measureText } from "../templates/layout";
import type { Role as FontRole } from "../templates/spec";
import type { Align } from "./scene";

export type Fitted = { size: number; lines: string[] };

// One text on the screen, as the layout found it: what it says, in which font and size, on which
// lines, and the box it fills at rest (without the slide of an entrance). `group` says which part
// of its block it belongs to (the beat of that part decides when it is visible), and `counts`
// whether its digits count up when the block's effect asks for it.
export type TextItem = {
  part: string;
  group: number;
  text: string;
  font: FontRole;
  size: number;
  lines: string[];
  box: Box;
  align: Align;
  colour: string;
  counts: boolean;
};

// The width of a text on one line at a font size of 1 px.
function unitWidth(text: string, font: FontRole): number {
  return measureText(text, font, 1);
}

// The words split onto `count` lines so that the widest line is as narrow as possible.
function bestSplit(words: string[], count: number, font: FontRole): string[] {
  const n = words.length;
  const widthOf = (from: number, to: number) => unitWidth(words.slice(from, to).join(" "), font);
  // widest[k][i]: the narrowest widest line of the first i words on k lines.
  const widest: number[][] = Array.from({ length: count + 1 }, () =>
    new Array<number>(n + 1).fill(Infinity),
  );
  const cut: number[][] = Array.from({ length: count + 1 }, () => new Array<number>(n + 1).fill(0));
  (widest[0] as number[])[0] = 0;
  for (let k = 1; k <= count; k += 1) {
    for (let i = k; i <= n; i += 1) {
      for (let j = k - 1; j < i; j += 1) {
        const value = Math.max((widest[k - 1] as number[])[j] ?? Infinity, widthOf(j, i));
        if (value < ((widest[k] as number[])[i] ?? Infinity)) {
          (widest[k] as number[])[i] = value;
          (cut[k] as number[])[i] = j;
        }
      }
    }
  }
  const lines: string[] = [];
  let end = n;
  for (let k = count; k >= 1; k -= 1) {
    const start = (cut[k] as number[])[end] ?? 0;
    lines.unshift(words.slice(start, end).join(" "));
    end = start;
  }
  return lines;
}

// How `text` is laid out in a space `boxW` x `boxH`: the largest whole pixel size, up to `base`,
// at which it fits on one line, or on up to `maxLines` lines split at word breaks. The widest
// line stays within 97 percent of the width (the margin of the templates).
export function fitText(
  text: string,
  font: FontRole,
  base: number,
  boxW: number,
  boxH: number,
  maxLines: number,
): Fitted {
  const words = text.split(/\s+/).filter((word) => word.length > 0);
  if (words.length === 0) return { size: base, lines: [""] };
  let best: Fitted | null = null;
  for (let count = 1; count <= Math.min(maxLines, words.length); count += 1) {
    const lines = bestSplit(words, count, font);
    const widest = Math.max(...lines.map((line) => unitWidth(line, font)));
    const size = Math.max(
      1,
      Math.min(
        base,
        widest > 0 ? Math.floor((FIT_SHARE * boxW) / widest) : base,
        Math.floor(boxH / (count * LINE_HEIGHT)),
      ),
    );
    if (best === null || size > best.size) best = { size, lines };
  }
  return best ?? { size: base, lines: [text] };
}

// The size of a number (its final text, never split): `base`, or the largest whole pixel size at
// which it is within 97 percent of the width and one line fits the height.
export function fitNumberIn(display: string, base: number, boxW: number, boxH: number): number {
  const unit = unitWidth(display, "display");
  const byWidth = unit > 0 ? Math.floor((FIT_SHARE * boxW) / unit) : base;
  return Math.max(1, Math.min(base, byWidth, Math.floor(boxH / LINE_HEIGHT)));
}

export function linesHeight(count: number, size: number): number {
  return count * size * LINE_HEIGHT;
}

// The box a text fills when it is placed in `area` (left to right) with its top at `top`.
export function placeText(
  lines: string[],
  font: FontRole,
  size: number,
  align: Align,
  area: { left: number; right: number },
  top: number,
): Box {
  const widest = Math.max(...lines.map((line) => measureText(line, font, size)));
  const left =
    align === "left"
      ? area.left
      : align === "center"
        ? (area.left + area.right - widest) / 2
        : area.right - widest;
  return {
    left: Math.round(left),
    top: Math.round(top),
    right: Math.round(left + widest),
    bottom: Math.round(top + linesHeight(lines.length, size)),
  };
}
