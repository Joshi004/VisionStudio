import { useEffect, useMemo, useRef, useState } from "react";
import type { ComponentType } from "react";
import { continueRender, delayRender, useCurrentFrame } from "remotion";

import { useFontsReady } from "../fonts";
import type { GraphicInput } from "../types";
import { TEXT_MARKER } from "./marker";
import { allowedRequire } from "./modules";
import { graphicProps } from "./props";
import type { GraphicProps } from "./props";

const TEXT_MAX_CHARS = 4000;

// Evaluates the transpiled component (CommonJS, from `server/transpile.ts`) and returns its default
// export. The code can reach only what `allowedRequire` hands it. The container is the security
// boundary (G-8); this only keeps an honest component honest.
export function loadComponent(compiled: string): ComponentType<GraphicProps> {
  const module: { exports: Record<string, unknown> } = { exports: {} };
  // eslint-disable-next-line no-new-func
  const run = new Function("require", "module", "exports", compiled) as (
    require: (name: string) => unknown,
    module: { exports: Record<string, unknown> },
    exports: Record<string, unknown>,
  ) => void;
  run(allowedRequire, module, module.exports);
  const component = module.exports["default"];
  if (typeof component !== "function" && (typeof component !== "object" || component === null)) {
    throw new Error("The component has no default export that React can draw.");
  }
  return component as ComponentType<GraphicProps>;
}

// What is on the screen as text: the visible text of the page and the text of SVG labels.
export function visibleText(root: HTMLElement): string {
  const svgTexts = Array.from(root.querySelectorAll("text"), (node) => node.textContent ?? "");
  return [root.innerText, ...svgTexts].join("\n").slice(0, TEXT_MAX_CHARS);
}

// The `Generated` composition (GFX-010): draws the model's component from `input.compiled` with the
// props of §4.5.3. In check mode (`report_text`) it also writes the text on screen to the console,
// for the backend's number rule. An error in the component fails the render with its message.
export function Generated(input: GraphicInput) {
  const frame = useCurrentFrame();
  const ready = useFontsReady();
  const root = useRef<HTMLDivElement>(null);
  const [wait] = useState(() =>
    input.report_text === true
      ? delayRender("Reading the text on screen", { timeoutInMilliseconds: 30_000 })
      : null,
  );
  const props = useMemo(() => graphicProps(input), [input]);
  const Component = useMemo(() => {
    if (!ready) return null;
    if (typeof input.compiled !== "string") {
      throw new Error("The render has no compiled component.");
    }
    return loadComponent(input.compiled);
  }, [ready, input.compiled]);

  useEffect(() => {
    if (wait === null || Component === null || root.current === null) return;
    console.log(TEXT_MARKER + JSON.stringify({ frame, text: visibleText(root.current) }));
    continueRender(wait);
  }, [wait, Component, frame]);

  // Under the component, so one that paints nothing is still on the lab's background.
  return (
    <div
      ref={root}
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        background: props.theme.background,
      }}
    >
      {Component !== null && <Component {...props} />}
    </div>
  );
}
