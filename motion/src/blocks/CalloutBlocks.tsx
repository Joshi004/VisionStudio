import { useMemo } from "react";
import { useCurrentFrame } from "remotion";

import type { CalloutResolved } from "../callout/props";
import type { GraphicInput } from "../types";
import { Piece } from "./Blocks";
import { calloutBlockInput, calloutOptions, readCalloutScene } from "./callout";
import { layoutScene } from "./layout";

// The block scene of a callout, drawn on the callout's transparent canvas (CMO-004): the same
// pieces as `Blocks`, but no background. The parent (`Callout`) paints the backdrop of a preview
// and applies the common exit fade. It is drawn only once the fonts are ready, so the layout is
// measured with the real fonts.
export function CalloutBlocks({
  input,
  callout,
  ready,
}: {
  input: GraphicInput;
  callout: CalloutResolved;
  ready: boolean;
}) {
  const frame = useCurrentFrame();
  const drawn = useMemo(() => {
    if (!ready) return null;
    const canvas = calloutBlockInput(input, callout);
    const scene = readCalloutScene(input.input, callout);
    return { scene, layout: layoutScene(canvas, scene, calloutOptions(callout)) };
  }, [ready, input, callout]);
  if (drawn === null) return null;

  return (
    <>
      {drawn.scene.elements.map((element, index) => {
        const entry = drawn.layout.laid[index];
        if (entry === undefined) return null;
        return (
          <Piece
            key={element.id}
            ctx={drawn.layout.ctx}
            frame={frame}
            scene={drawn.scene}
            element={element}
            entry={entry}
          />
        );
      })}
    </>
  );
}
