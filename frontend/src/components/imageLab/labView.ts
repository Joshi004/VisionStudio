import {
  MAX_REFERENCES,
  PRICE_PER_IMAGE_USD,
  type LabImage,
  type LabMode,
  type LabRun,
  type LabRunRequest,
  type ProjectFrame,
} from "../../api/imageLab";

/** An image that will be sent as a reference, with what is needed to show it. */
export type ReferenceItem = {
  source: "lab" | "asset";
  id: number;
  url: string;
  width: number | null;
  height: number | null;
  /** "lab image 3" or "project frame 73": what the thumbnail's caption says. */
  label: string;
};

export type LabFormState = {
  mode: LabMode;
  model: string;
  prompt: string;
  /** A preset's value, or "custom" (then `customSize` is used). */
  sizePreset: string;
  customSize: string;
  watermark: "off" | "on" | "unset";
  /** Empty: not sent. */
  seed: string;
  /** Empty: no image set. */
  setMax: string;
  imageFieldAs: "list" | "string";
  editFieldName: "image" | "image[]";
  extraJson: string;
  references: ReferenceItem[];
};

export const MODE_LABELS: Record<LabMode, string> = {
  text_to_image: "Text to image",
  image_to_image: "Image to image",
  edit: "Edit (multipart)",
};

/** What each mode calls, and what was seen when it was last tested. */
export const MODE_NOTES: Record<LabMode, string> = {
  text_to_image:
    "POST /images/generations with a prompt only. Tested on 8 Oct 2026: it works, one image in 25 to 36 s.",
  image_to_image:
    "POST /images/generations with the references in the image field. Tested on 8 Oct 2026: the field was accepted and ignored, the result did not use the references.",
  edit:
    "POST /images/edits as a multipart form, one file part per reference. Tested on 8 Oct 2026: Cloudflare's bot check refused every file upload.",
};

export const SIZE_PRESETS = [
  { value: "1632x2880", label: "Portrait 1632 x 2880 (1.5 x the 1088 x 1920 size)" },
  { value: "1632x3072", label: "Portrait 1632 x 3072 (a strip at the bottom to crop the watermark)" },
  { value: "2880x1632", label: "Landscape 2880 x 1632" },
  { value: "3264x3072", label: "Two portrait panels, 3264 x 3072" },
  { value: "2K", label: "2K" },
  { value: "3K", label: "3K" },
  { value: "custom", label: "Custom..." },
];

export const DEFAULT_MODEL = "seedream-5.0-lite";

export const DEFAULT_FORM: LabFormState = {
  mode: "text_to_image",
  model: DEFAULT_MODEL,
  prompt: "",
  sizePreset: "1632x2880",
  customSize: "",
  watermark: "off",
  seed: "",
  setMax: "",
  imageFieldAs: "list",
  editFieldName: "image",
  extraJson: "",
  references: [],
};

export function sizeOf(state: LabFormState): string {
  return state.sizePreset === "custom" ? state.customSize.trim() : state.sizePreset;
}

export type ExtraResult = { value: Record<string, unknown>; error: null } | { value: null; error: string };

/** The "extra JSON" box: empty is fine, anything else must be a JSON object. */
export function parseExtra(text: string): ExtraResult {
  if (text.trim() === "") {
    return { value: {}, error: null };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { value: null, error: "This is not valid JSON." };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { value: null, error: 'It must be a JSON object, like {"guidance_scale": 7.5}.' };
  }
  const blocked = ["model", "prompt", "image"].filter((key) => key in parsed);
  if (blocked.length > 0) {
    return { value: null, error: `It cannot hold ${blocked.join(", ")}: the form sets those.` };
  }
  return { value: parsed as Record<string, unknown>, error: null };
}

function wholeNumber(text: string): number | null {
  return /^-?\d+$/.test(text.trim()) ? Number(text.trim()) : null;
}

/** Why Run cannot be pressed now, or null. The server checks everything again. */
export function blockedReason(state: LabFormState): string | null {
  if (state.prompt.trim() === "") {
    return "Write a prompt.";
  }
  if (state.model.trim() === "") {
    return "Enter a model.";
  }
  if (!/^(\d{1,5}x\d{1,5}|\d(\.\d)?[Kk])$/.test(sizeOf(state))) {
    return 'The size must look like "1632x2880" or "2K".';
  }
  if (state.seed.trim() !== "" && wholeNumber(state.seed) === null) {
    return "The seed must be a whole number.";
  }
  if (state.setMax.trim() !== "") {
    const count = wholeNumber(state.setMax);
    if (count === null || count < 1 || count > 15) {
      return "An image set holds 1 to 15 images.";
    }
  }
  if (parseExtra(state.extraJson).error !== null) {
    return "Fix the extra JSON.";
  }
  const count = state.references.length;
  if (state.mode !== "text_to_image" && count === 0) {
    return "Add at least one reference image.";
  }
  if (state.mode !== "text_to_image" && count > MAX_REFERENCES) {
    return `At most ${MAX_REFERENCES} references.`;
  }
  if (state.mode === "image_to_image" && state.imageFieldAs === "string" && count !== 1) {
    return "Sending the image as a string takes exactly one reference.";
  }
  return null;
}

/** The images a run is expected to make: the image set's maximum, or one. */
export function expectedImages(state: LabFormState): number {
  return wholeNumber(state.setMax) ?? 1;
}

function money(amount: number): string {
  return `$${amount.toFixed(3)}`;
}

/** "about $0.035", or "up to $0.105" for an image set. An estimate from Bitdeer's price list. */
export function costText(state: LabFormState): string {
  const images = expectedImages(state);
  const total = images * PRICE_PER_IMAGE_USD;
  return images > 1 ? `up to ${money(total)}` : `about ${money(total)}`;
}

/** The form as the request the server takes. References are sent only in the modes that use them. */
export function toRequest(state: LabFormState): LabRunRequest {
  const extra = parseExtra(state.extraJson).value ?? {};
  const seed = wholeNumber(state.seed);
  const setMax = wholeNumber(state.setMax);
  return {
    mode: state.mode,
    model: state.model.trim(),
    prompt: state.prompt,
    size: sizeOf(state),
    watermark: state.watermark === "unset" ? null : state.watermark === "on",
    seed,
    sequential_max_images: setMax,
    image_field_as: state.imageFieldAs,
    edit_field_name: state.editFieldName,
    extra,
    references:
      state.mode === "text_to_image"
        ? []
        : state.references.map((item) => ({ source: item.source, id: item.id })),
  };
}

export function referenceFromImage(image: LabImage): ReferenceItem {
  return {
    source: "lab",
    id: image.id,
    url: image.url,
    width: image.width,
    height: image.height,
    label: image.origin === "upload" ? `upload ${image.id}` : `result of run ${image.run_id ?? "?"}`,
  };
}

export function referenceFromFrame(frame: ProjectFrame): ReferenceItem {
  const use =
    frame.scene_number !== null ? `scene ${frame.scene_number}, ${frame.slot} frame` : frame.source;
  return {
    source: "asset",
    id: frame.asset_id,
    url: frame.url,
    width: frame.width,
    height: frame.height,
    label: `project frame ${frame.asset_id} (${use})`,
  };
}

/** Adds items that are not in the list yet, up to the limit. Says what was left out, if anything. */
export function addReferences(
  current: ReferenceItem[],
  added: ReferenceItem[],
): { items: ReferenceItem[]; note: string | null } {
  const items = [...current];
  let skipped = 0;
  let duplicates = 0;
  for (const item of added) {
    if (items.some((have) => have.source === item.source && have.id === item.id)) {
      duplicates += 1;
    } else if (items.length >= MAX_REFERENCES) {
      skipped += 1;
    } else {
      items.push(item);
    }
  }
  const notes: string[] = [];
  if (duplicates > 0) {
    notes.push(`${duplicates} already in the list`);
  }
  if (skipped > 0) {
    notes.push(`${skipped} not added: at most ${MAX_REFERENCES} references`);
  }
  return { items, note: notes.length > 0 ? `${notes.join("; ")}.` : null };
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** What a past run held, as form state, so it can be run again or varied. */
export function stateFromRun(run: LabRun): LabFormState {
  const params = run.params;
  const size = text(params.size);
  const preset = SIZE_PRESETS.some((option) => option.value === size && option.value !== "custom");
  const extra = params.extra;
  const hasExtra = typeof extra === "object" && extra !== null && Object.keys(extra).length > 0;
  return {
    mode: run.mode,
    model: run.model,
    prompt: run.prompt,
    sizePreset: preset ? size : "custom",
    customSize: preset ? "" : size,
    watermark: params.watermark === true ? "on" : params.watermark === false ? "off" : "unset",
    seed: typeof params.seed === "number" ? String(params.seed) : "",
    setMax:
      typeof params.sequential_max_images === "number" ? String(params.sequential_max_images) : "",
    imageFieldAs: params.image_field_as === "string" ? "string" : "list",
    editFieldName: params.edit_field_name === "image[]" ? "image[]" : "image",
    extraJson: hasExtra ? JSON.stringify(extra, null, 2) : "",
    references: run.references.flatMap((reference) =>
      reference.url === null
        ? []
        : [
            {
              source: reference.source,
              id: reference.id,
              url: reference.url,
              width: reference.width,
              height: reference.height,
              label:
                reference.source === "lab"
                  ? `lab image ${reference.id}`
                  : `project frame ${reference.id}`,
            },
          ],
    ),
  };
}

/** "seed 42, watermark off, 1632x2880": the settings of a run on one line. */
export function paramsLine(run: LabRun): string {
  const params = run.params;
  const parts: string[] = [text(params.size)];
  parts.push(
    params.watermark === true
      ? "watermark on"
      : params.watermark === false
        ? "watermark off"
        : "watermark not sent",
  );
  if (typeof params.seed === "number") {
    parts.push(`seed ${params.seed}`);
  }
  if (typeof params.sequential_max_images === "number") {
    parts.push(`image set of up to ${params.sequential_max_images}`);
  }
  return parts.filter((part) => part !== "").join(" · ");
}

export function costLine(run: LabRun): string | null {
  return run.estimated_cost_usd === null ? null : `about ${money(run.estimated_cost_usd)} (estimate)`;
}
