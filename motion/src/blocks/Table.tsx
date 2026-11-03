import type { Box } from "../types";
import { boxHeight, boxWidth, measureOf } from "./ctx";
import type { BCtx } from "./ctx";
import { fitNumberIn, fitText, linesHeight, placeText } from "./fit";
import type { TextItem } from "./fit";
import { Item } from "./Item";
import type { TableEl } from "./scene";

export type TableLaid = {
  kind: "table";
  id: string;
  box: Box;
  texts: TextItem[];
  // The y of the lines between rows.
  rules: number[];
};

// A grid of up to 5 rows and 4 columns (the header is one more row). Every column has the same
// width and every row the same height. A cell is one line of text, left aligned, or a number
// (a fact or a derived value), right aligned. All cells have one size: the smallest that any of
// them needs.
export function layoutTable(ctx: BCtx, element: TableEl, box: Box): TableLaid {
  const rows = [...(element.header === undefined ? [] : [element.header]), ...element.rows];
  const hasHeader = element.header !== undefined;
  const columns = Math.max(...rows.map((row) => row.length));
  const columnWidth = boxWidth(box) / columns;
  const rowHeight = boxHeight(box) / rows.length;
  const pad = Math.round(0.01 * ctx.height);
  const inner = columnWidth - 2 * pad;

  type Cell = { text: string; ref: boolean; row: number; column: number };
  const cells: Cell[] = [];
  rows.forEach((row, rowIndex) => {
    row.forEach((cell, column) => {
      if (typeof cell === "string") cells.push({ text: cell, ref: false, row: rowIndex, column });
      else cells.push({ text: measureOf(ctx, cell.value).display, ref: true, row: rowIndex, column });
    });
  });
  const size = Math.min(
    ...cells.map((cell) =>
      cell.ref
        ? fitNumberIn(cell.text, ctx.bodySize, inner, rowHeight)
        : fitText(cell.text, "text", ctx.bodySize, inner, rowHeight, 1).size,
    ),
  );
  const texts: TextItem[] = cells.map((cell) => {
    const left = box.left + cell.column * columnWidth + pad;
    const top = box.top + cell.row * rowHeight + (rowHeight - linesHeight(1, size)) / 2;
    const header = hasHeader && cell.row === 0;
    const source = rows[cell.row]?.[cell.column];
    const counts = cell.ref && typeof source === "object" && measureOf(ctx, source.value).unit !== "none";
    return {
      part: `cell.${cell.row}.${cell.column}`,
      group: 0,
      text: cell.text,
      font: cell.ref ? "display" : "text",
      size,
      lines: [cell.text],
      box: placeText(
        [cell.text],
        cell.ref ? "display" : "text",
        size,
        cell.ref ? "right" : "left",
        { left, right: left + inner },
        top,
      ),
      align: cell.ref ? "right" : "left",
      colour: header ? ctx.theme.muted : ctx.theme.text,
      counts,
    };
  });
  const rules = Array.from({ length: rows.length - 1 }, (_unused, index) =>
    Math.round(box.top + (index + 1) * rowHeight),
  );
  return { kind: "table", id: element.id, box, texts, rules };
}

export function DrawTable({ ctx, l }: { ctx: BCtx; l: TableLaid }) {
  return (
    <>
      {l.rules.map((y) => (
        <div
          key={y}
          style={{
            position: "absolute",
            left: l.box.left,
            top: y,
            width: boxWidth(l.box),
            height: ctx.stroke,
            background: ctx.theme.surface,
          }}
        />
      ))}
      {l.texts.map((item) => (
        <Item key={item.part} item={item} />
      ))}
    </>
  );
}
