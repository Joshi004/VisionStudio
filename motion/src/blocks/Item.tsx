import { LINE_HEIGHT, family } from "../templates/layout";
import { countedText } from "../templates/motion";
import type { TextItem } from "./fit";

// The characters of a text that a typewriter has typed by now, kept on the lines the layout chose
// (a space between two lines counts as one character), so nothing moves while it types.
function typed(lines: string[], count: number): string[] {
  let left = count;
  return lines.map((line) => {
    const shown = line.slice(0, Math.max(0, left));
    left -= line.length + 1;
    return shown;
  });
}

// A text, drawn exactly as the layout found it: its font, size and lines, in its box. `count` is
// how far a number has counted (0 to 1; 1 for a text that does not count) and `typed` how much of
// a typewriter's text is shown (0 to 1).
export function Item({
  item,
  count = 1,
  typedShare = 1,
}: {
  item: TextItem;
  count?: number;
  typedShare?: number;
}) {
  const lineHeight = item.size * LINE_HEIGHT;
  let lines = item.lines;
  if (typedShare < 1) {
    const total = item.lines.reduce((sum, line) => sum + line.length + 1, -1);
    lines = typed(item.lines, Math.ceil(total * typedShare));
  }
  if (item.counts && count < 1 && lines.length === 1) {
    lines = [countedText(item.text, count, true)];
  }
  return (
    <div
      style={{
        position: "absolute",
        left: item.box.left,
        top: item.box.top,
        width: Math.ceil(item.box.right - item.box.left) + 2,
        // A number's box has the width of its final text, and its digits count up inside it from
        // the left edge, so nothing moves while it counts.
        textAlign: item.counts ? "left" : item.align,
        color: item.colour,
        fontFamily: family(item.font),
        fontSize: item.size,
      }}
    >
      {lines.map((line, index) => (
        <div
          key={index}
          style={{ height: lineHeight, lineHeight: `${lineHeight}px`, whiteSpace: "nowrap" }}
        >
          {line}
        </div>
      ))}
    </div>
  );
}
