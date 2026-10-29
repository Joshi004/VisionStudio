import type { CalloutRole, CalloutType } from "../../api/calloutPlan";

export const TYPE_LABELS: Record<CalloutType, string> = {
  emphasis: "Key idea",
  number: "Number",
  question: "Question",
  comparison: "Comparison",
  list: "List",
  section_title: "Section title",
};

export const TYPE_OPTIONS = (Object.keys(TYPE_LABELS) as CalloutType[]).map((value) => ({
  value,
  label: TYPE_LABELS[value],
}));

export const ROLE_LABELS: Record<CalloutRole, string> = {
  accent: "Accent",
  number: "Number (amber)",
  negative: "Negative (red)",
  positive: "Positive (green)",
};

export const ROLE_OPTIONS = (Object.keys(ROLE_LABELS) as CalloutRole[]).map((value) => ({
  value,
  label: ROLE_LABELS[value],
}));

/** The fixed colours of the roles (E-18). The accent comes from the plan itself. */
const FIXED_ROLE_COLOURS: Record<Exclude<CalloutRole, "accent">, string> = {
  number: "#FFB300",
  negative: "#E5484D",
  positive: "#2FB344",
};

export function roleColour(role: CalloutRole, accent: string): string {
  return role === "accent" ? accent : FIXED_ROLE_COLOURS[role];
}

/**
 * The most characters of each kind of text. The server checks them again; these only stop the
 * input from taking more.
 */
export const TEXT_MAX_CHARS = {
  emphasis: 32,
  number: 20,
  question: 48,
  section_title: 32,
} as const;
export const ITEM_MAX_CHARS = 24;
export const SIDE_MAX_CHARS = 24;
export const MIN_ITEMS = 2;
export const MAX_ITEMS = 3;

/** Seconds as m:ss. */
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  const rest = String(whole % 60).padStart(2, "0");
  return `${minutes}:${rest}`;
}
