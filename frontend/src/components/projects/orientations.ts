/** The video sizes a project can have. Chosen when the project is created and never changed. */
export const ORIENTATIONS = [
  { value: "landscape", label: "Landscape", size: "1920 x 1080" },
  { value: "portrait", label: "Portrait", size: "1080 x 1920" },
] as const;

export type Orientation = (typeof ORIENTATIONS)[number]["value"];

export function isOrientation(value: string): value is Orientation {
  return ORIENTATIONS.some((option) => option.value === value);
}
