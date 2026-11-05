// The template spec that GFX-006 stores (§4.5.1 of Graphics_lab_implementation_phases.md) and the
// checks the composition makes before it draws it. The backend has already checked the spec in
// depth (`graphics_templates.check_spec`); this file only makes sure the spec is the catalogue's
// version and has the parts the drawing code reads, so a wrong input fails with a clear message.
//
// The motion server imports this file with its `.ts` extension (Node's type stripping), so it only
// uses syntax that can be erased.

// The version of the catalogue this renderer draws. /health reports it, and a spec written for
// another version is refused. The same number is `graphics_templates.CATALOGUE_VERSION`.
export const CATALOGUE_VERSION = 1;

export type Role = "display" | "text";

// How one text is laid out: its font, its size in pixels and its lines (decided in GFX-006).
export type TextLayout = { font: Role; size: number; lines: string[] };

type Common = { catalogue_version: number; text: Record<string, TextLayout> };

export type KpiSpec = Common & {
  template: "kpi_card";
  variant: "center" | "split";
  fields: { title: string; value: string; change?: string; caption?: string };
  beats: { title: string; value: string; change?: string; caption?: string };
};

export type BarSpec = Common & {
  template: "bar_comparison";
  variant: "vertical" | "horizontal";
  fields: {
    title: string;
    bars: { label: string; value: string; emphasis?: boolean }[];
    highlight?: { value: string; beat: string };
  };
  beats: { title: string; bars: string[] };
};

export type LineSpec = Common & {
  template: "line_trend";
  variant: "line" | "area";
  fields: {
    title: string;
    points: { label: string; value: string }[];
    end_label?: string;
  };
  beats: { title: string; points: string[]; end_label?: string };
};

export type FlowSpec = Common & {
  template: "flow_diagram";
  variant: "horizontal" | "vertical";
  fields: { title: string; nodes: { label: string; beat: string }[] };
  beats: { title: string };
};

export type BulletSpec = Common & {
  template: "bullet_build";
  variant: "list" | "statement";
  fields: { title?: string; items: { text: string; beat: string }[] };
  beats: { title?: string };
};

export type TemplateSpec = KpiSpec | BarSpec | LineSpec | FlowSpec | BulletSpec;

const VARIANTS: Record<TemplateSpec["template"], readonly string[]> = {
  kpi_card: ["center", "split"],
  bar_comparison: ["vertical", "horizontal"],
  line_trend: ["line", "area"],
  flow_diagram: ["horizontal", "vertical"],
  bullet_build: ["list", "statement"],
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// The spec a render's `input` holds, or an Error that says what is wrong with it.
export function readSpec(input: unknown): TemplateSpec {
  if (!isObject(input)) throw new Error("The template spec is missing from the render's input.");
  const template = input["template"];
  if (template === null) {
    throw new Error("The spec says no template fits, so there is nothing to draw.");
  }
  if (typeof template !== "string" || !(template in VARIANTS)) {
    throw new Error(`The template ${JSON.stringify(template)} is not in the catalogue.`);
  }
  if (input["catalogue_version"] !== CATALOGUE_VERSION) {
    throw new Error(
      `The spec was written for catalogue version ${String(input["catalogue_version"])}; ` +
        `this renderer draws version ${CATALOGUE_VERSION}.`,
    );
  }
  const variants = VARIANTS[template as TemplateSpec["template"]];
  if (typeof input["variant"] !== "string" || !variants.includes(input["variant"])) {
    throw new Error(`The variant ${JSON.stringify(input["variant"])} of ${template} is unknown.`);
  }
  for (const key of ["fields", "beats", "text"]) {
    if (!isObject(input[key])) throw new Error(`The spec has no "${key}".`);
  }
  return input as unknown as TemplateSpec;
}
