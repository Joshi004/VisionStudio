import * as paths from "@remotion/paths";
import * as shapes from "@remotion/shapes";
import * as react from "react";
import * as jsxRuntime from "react/jsx-runtime";
import * as remotion from "remotion";

// The only modules a generated component may import (§4.5.3, decided in GFX-010). The backend's
// static checks refuse any other import before anything runs; this map is the second guard: the
// component is evaluated with a `require` that knows nothing else. `react/jsx-runtime` is not
// listed for the model: the transpiler's automatic JSX transform imports it.
const ALLOWED: Record<string, unknown> = {
  react,
  remotion,
  "@remotion/shapes": shapes,
  "@remotion/paths": paths,
  "react/jsx-runtime": jsxRuntime,
};

export function allowedRequire(name: string): unknown {
  if (Object.hasOwn(ALLOWED, name)) return ALLOWED[name];
  throw new Error(`Import not allowed: "${name}". Only react, remotion, @remotion/shapes and @remotion/paths may be imported.`);
}
