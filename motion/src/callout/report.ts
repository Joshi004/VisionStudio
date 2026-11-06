// The text of a callout that is cut off, measured in the page in check mode (CMO-001).

const TOLERANCE_PX = 1;
const REPORT_TEXT_CHARS = 80;

type Rect = { left: number; top: number; right: number; bottom: number };

function leaves(outer: Rect, inner: DOMRect): boolean {
  return (
    inner.left < outer.left - TOLERANCE_PX ||
    inner.top < outer.top - TOLERANCE_PX ||
    inner.right > outer.right + TOLERANCE_PX ||
    inner.bottom > outer.bottom + TOLERANCE_PX
  );
}

// Whether a text's own box is clipped by an ancestor (one whose `overflow` is not `visible`, the
// root included) or ends in an ellipsis that hides part of it.
function isCut(node: Text, root: HTMLElement): boolean {
  const range = document.createRange();
  range.selectNodeContents(node);
  const box = range.getBoundingClientRect();
  // Text that takes no room (an empty line, `display: none`) cannot be cut.
  if (box.width === 0 || box.height === 0) return false;

  const rootBox = root.getBoundingClientRect();
  if (leaves(rootBox, box)) return true;

  for (let element = node.parentElement; element !== null; element = element.parentElement) {
    const style = getComputedStyle(element);
    if (style.textOverflow === "ellipsis" && element.scrollWidth > element.clientWidth + TOLERANCE_PX) return true;
    if (element !== root && (style.overflowX !== "visible" || style.overflowY !== "visible")) {
      if (leaves(element.getBoundingClientRect(), box)) return true;
    }
    if (element === root) break;
  }
  return false;
}

// The texts (shortened) of every text node of `root` that is cut: HTML text and SVG `<text>`.
export function cutTexts(root: HTMLElement): string[] {
  const found: string[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
    const text = (node.textContent ?? "").trim();
    if (text === "") continue;
    if (isCut(node as Text, root)) found.push(text.slice(0, REPORT_TEXT_CHARS));
  }
  return found;
}
