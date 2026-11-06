// The block library in callout mode (CMO-004, §4.4.2 of Callouts_motion_implementation_phases.md).
//
// A callout is drawn on a transparent canvas the size of its zone. The same blocks and the same
// layout code are used as for a graphic shot, with these differences, all made here and in the
// options that `layoutScene` takes: the grid is built from the canvas less a small inset (no caption
// band, no background); the text sizes read the output frame, not the zone; the scene names parts
// of the callout instead of writing text; and the callout look sets the corners and the panel.
// A shot graphic never reaches this file, so its scenes are drawn exactly as before.
import type { CalloutPart, CalloutResolved } from "../callout/props";
import type { GraphicInput, Resolved } from "../types";
import type { CtxOptions } from "./ctx";
import type { Element, Scene } from "./scene";

// The same number is `graphics_blocks.CALLOUT_INSET_SHARE`: each side of the canvas is left free by
// this share of the output frame's height.
export const CALLOUT_INSET_SHARE = 0.01;

// The blocks a callout scene may hold. `counter`, the series, `table` and `progress_ring` need
// values, which a callout does not have.
export const CALLOUT_BLOCKS = ["text", "badge", "node", "arrow", "highlight", "panel"];

// The layout options of a callout: the text sizes, the corners and the panel from its look.
export function calloutOptions(callout: CalloutResolved): CtxOptions {
  if (callout.frame_width === undefined) {
    throw new Error("The callout's resolved brief has no frame_width, which a block scene needs.");
  }
  return {
    frameWidth: callout.frame_width,
    frameHeight: callout.frame_height,
    corners: callout.look["corners"] ?? "soft",
    panelOpacity: callout.look["panel"] === "glass" ? 0.75 : 1,
  };
}

// The render's input with the resolved brief that the blocks read: a safe area that is the canvas
// less the inset, no caption band, `surface` as the background colour (a badge's text), and one
// beat for each part, at the part's frame.
export function calloutBlockInput(input: GraphicInput, callout: CalloutResolved): GraphicInput {
  if (callout.motion === undefined) {
    throw new Error("The callout's resolved brief has no motion, which a block scene needs.");
  }
  const inset = Math.round(CALLOUT_INSET_SHARE * callout.frame_height);
  const beats: Resolved["beats"] = {};
  for (const part of callout.parts) beats[part.id] = { frame: part.frame, shows: part.text };
  const resolved: Resolved = {
    width: input.width,
    height: input.height,
    fps: input.fps,
    frames: input.frames,
    facts: {},
    derived: {},
    beats,
    theme: {
      background: callout.theme.surface,
      surface: callout.theme.surface,
      text: callout.theme.text,
      muted: callout.theme.muted,
      accent: callout.theme.accent,
      positive: callout.theme.positive,
      negative: callout.theme.negative,
      number: callout.theme.number,
      background_style: "solid",
      motion: callout.motion,
    },
    fonts: callout.fonts,
    safe_area: { left: inset, top: inset, right: input.width - inset, bottom: input.height - inset },
    caption_zone: { top: input.height, bottom: input.height },
  };
  return { ...input, resolved };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function partOf(parts: CalloutPart[], element: Record<string, unknown>): CalloutPart {
  const found = parts.find((part) => part.id === element["part"]);
  if (found === undefined) {
    throw new Error(`The element ${String(element["id"])} names the part ${JSON.stringify(element["part"])}, which the callout does not have.`);
  }
  return found;
}

// The scene that a callout's render holds as `input`, made into a scene the block library lays out:
// every element that shows a part gets the part's text and colour, and the panels come first, so
// they are drawn under the other elements. The backend has checked the scene in depth
// (`graphics_blocks.check_callout_scene`); this makes sure it is a callout scene.
export function readCalloutScene(input: unknown, callout: CalloutResolved): Scene {
  if (!isObject(input) || !Array.isArray(input["elements"]) || input["elements"].length === 0) {
    throw new Error("The callout's block scene has no elements.");
  }
  const elements = input["elements"].map((item): Element => {
    if (!isObject(item) || typeof item["id"] !== "string") {
      throw new Error("An element of the callout's block scene has no id.");
    }
    const block = item["block"];
    if (typeof block !== "string" || !CALLOUT_BLOCKS.includes(block)) {
      throw new Error(`The block ${JSON.stringify(block)} is not in the callout block library.`);
    }
    if (!isObject(item["enter"]) || typeof item["enter"]["effect"] !== "string") {
      throw new Error(`The element ${item["id"]} has no entrance.`);
    }
    if (block === "text") {
      const part = partOf(callout.parts, item);
      return { ...item, text: part.text, colour: part.colour } as unknown as Element;
    }
    if (block === "badge") {
      const part = partOf(callout.parts, item);
      return { ...item, text: part.text, colour: part.colour } as unknown as Element;
    }
    if (block === "node") {
      const part = partOf(callout.parts, item);
      return { ...item, label: part.text, colour: part.colour } as unknown as Element;
    }
    return item as unknown as Element;
  });
  const panels = elements.filter((element) => element.block === "panel");
  const others = elements.filter((element) => element.block !== "panel");
  return { blocks_version: 1, elements: [...panels, ...others] };
}
