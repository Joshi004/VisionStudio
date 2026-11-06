// The layout report of `POST /layout` (§4.5.2, "Layout check"): the texts that are on the screen at
// the frames asked for, each with its font, size and the box it fills at rest. The backend decides
// from it whether the scene has a layout problem (`graphics_blocks.layout_problems`).
import type { Box, GraphicInput } from "../types";
import { enterProgress, exitProgress } from "./effects";
import type { CtxOptions } from "./ctx";
import { layoutScene } from "./layout";
import type { Issue } from "./layout";
import type { Scene } from "./scene";

export type ReportText = {
  element: string;
  part: string;
  text: string;
  font: string;
  size: number;
  box: Box;
};

export type LayoutReport = {
  frames: { frame: number; texts: ReportText[] }[];
  issues: Issue[];
};

// An element that has begun to leave is not counted: another may take its place on the same beat.
export function layoutReport(
  input: GraphicInput,
  scene: Scene,
  frames: number[],
  options?: CtxOptions,
): LayoutReport {
  const layout = layoutScene(input, scene, options);
  const { ctx } = layout;
  return {
    frames: frames.map((frame) => {
      const texts: ReportText[] = [];
      scene.elements.forEach((element, index) => {
        const entry = layout.laid[index];
        if (entry === undefined || exitProgress(ctx, frame, element) > 0) return;
        const parts = enterProgress(ctx, frame, element);
        for (const item of entry.texts) {
          if ((parts[item.group] ?? parts[0] ?? 0) <= 0) continue;
          texts.push({
            element: element.id,
            part: item.part,
            text: item.lines.join(" "),
            font: item.font,
            size: item.size,
            box: item.box,
          });
        }
      });
      return { frame, texts };
    }),
    issues: layout.issues,
  };
}
