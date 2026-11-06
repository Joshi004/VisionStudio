import { useEffect, useMemo, useRef, useState } from "react";
import type { ComponentType } from "react";
import { continueRender, delayRender, interpolate, useCurrentFrame } from "remotion";

import { CalloutBlocks } from "../blocks/CalloutBlocks";
import { useFontsReady } from "../fonts";
import { loadComponent, visibleText } from "../generated/Generated";
import type { GraphicInput } from "../types";
import { CALLOUT_MARKER } from "./marker";
import { calloutProps, readCallout } from "./props";
import type { CalloutProps } from "./props";
import { cutTexts } from "./report";

// The `Callout` composition (CMO-001): a callout drawn on a canvas the size of its zone. The canvas
// is transparent, so the video can be laid over a shot. Only a preview (`resolved.backdrop`) paints
// a colour under the callout, so that an ordinary H.264 file can show it.
//
// Both versions of a callout (§4.4) are drawn here: the generated component (`callout_component`)
// and the building blocks (`callout_blocks`, CMO-004). Whatever the version, the same exit fade
// ends the callout (CM-7).
export function Callout(input: GraphicInput) {
  const frame = useCurrentFrame();
  const ready = useFontsReady();
  const root = useRef<HTMLDivElement>(null);
  const checking = input.report_callout === true;
  const [wait] = useState(() =>
    checking ? delayRender("Reading the callout", { timeoutInMilliseconds: 30_000 }) : null,
  );
  const callout = useMemo(() => readCallout(input), [input]);
  const props = useMemo(() => calloutProps(input, callout), [input, callout]);
  const Component = useMemo(() => {
    if (!ready) return null;
    if (input.engine === "callout_blocks") return null;
    if (input.engine !== "callout_component") {
      throw new Error(`The Callout composition cannot draw the engine "${input.engine}".`);
    }
    if (typeof input.compiled !== "string") throw new Error("The render has no compiled component.");
    return loadComponent(input.compiled) as unknown as ComponentType<CalloutProps>;
  }, [ready, input.engine, input.compiled]);

  useEffect(() => {
    if (wait === null || Component === null || root.current === null) return;
    const report = { frame, text: visibleText(root.current), cut: cutTexts(root.current) };
    console.log(CALLOUT_MARKER + JSON.stringify(report));
    continueRender(wait);
  }, [wait, Component, frame]);

  // Nothing is shown from `exit_frame` on: the fade ends on the last frame.
  const opacity = interpolate(frame, [callout.exit_frame, input.frames - 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  // A check measures the transparent canvas, so it never paints a backdrop.
  const background = !checking && callout.backdrop !== undefined ? callout.backdrop : "transparent";

  return (
    <div ref={root} style={{ position: "absolute", inset: 0, overflow: "hidden", background }}>
      <div style={{ position: "absolute", inset: 0, opacity }}>
        {Component !== null && <Component {...props} />}
        {input.engine === "callout_blocks" && <CalloutBlocks input={input} callout={callout} ready={ready} />}
      </div>
    </div>
  );
}
