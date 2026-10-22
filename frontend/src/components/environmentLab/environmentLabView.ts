import type { EnvironmentIn, EnvironmentVersion, LibraryEnvironment } from "../../api/environmentLab";

/** Pure helpers for the environment library: words, form state and the same checks as the server. */

export type EraKind = LibraryEnvironment["era_kind"];

export const LIMITS = {
  name: 80,
  description: 2500,
  atmosphere: 500,
  notes: 1000,
  eraSetting: 200,
  eraYearsMax: 10_000,
} as const;

/** What a version changed compared with the one before it, in words. */
export const VERSION_CHANGE_LABELS: Record<EnvironmentVersion["changes"][number], string> = {
  created: "Created",
  profile: "Profile",
  definition: "Definition",
  states: "States",
};

/** The time an environment is set in, in words. */
export function eraText(
  environment: Pick<LibraryEnvironment, "era_kind" | "era_years" | "era_setting">,
): string {
  const setting = environment.era_setting ? `, ${environment.era_setting}` : "";
  if (environment.era_kind === "present") {
    return `Present${setting}`;
  }
  const direction = environment.era_kind === "past" ? "in the past" : "in the future";
  return `About ${environment.era_years ?? "?"} years ${direction}${setting}`;
}

// --- The form ----------------------------------------------------------------------------------

export type EnvironmentFormState = {
  name: string;
  description: string;
  eraKind: EraKind;
  /** Typed in a box, so it is text until it is sent. */
  eraYears: string;
  eraSetting: string;
  atmosphere: string;
  notes: string;
};

export const DEFAULT_FORM: EnvironmentFormState = {
  name: "",
  description: "",
  eraKind: "present",
  eraYears: "",
  eraSetting: "",
  atmosphere: "",
  notes: "",
};

export function formFromEnvironment(environment: LibraryEnvironment): EnvironmentFormState {
  return {
    name: environment.name,
    description: environment.description,
    eraKind: environment.era_kind,
    eraYears: environment.era_years === null ? "" : String(environment.era_years),
    eraSetting: environment.era_setting ?? "",
    atmosphere: environment.atmosphere ?? "",
    notes: environment.notes ?? "",
  };
}

/** A whole number typed in a box, or null when it is not one. Empty is not a number. */
function wholeNumber(value: string): number | null {
  const text = value.trim();
  if (!/^-?\d{1,15}$/.test(text)) {
    return null;
  }
  return Number(text);
}

function tooLong(value: string, limit: number, what: string): string | null {
  return value.length > limit
    ? `The ${what} must be at most ${limit.toLocaleString()} characters.`
    : null;
}

/** The first thing wrong with the form, or null. Same rules as the server. */
export function formProblem(form: EnvironmentFormState): string | null {
  if (form.name.trim() === "") {
    return "Give the environment a name.";
  }
  if (form.description.trim() === "") {
    return "Describe what the environment looks like.";
  }
  const long = [
    tooLong(form.name, LIMITS.name, "name"),
    tooLong(form.description, LIMITS.description, "description"),
    tooLong(form.atmosphere, LIMITS.atmosphere, "atmosphere"),
    tooLong(form.notes, LIMITS.notes, "notes"),
    tooLong(form.eraSetting, LIMITS.eraSetting, "era setting"),
  ].find((message) => message !== null);
  if (long) {
    return long;
  }
  if (form.eraKind !== "present") {
    const years = wholeNumber(form.eraYears);
    if (years === null || years < 1 || years > LIMITS.eraYearsMax) {
      return `Give the number of years, from 1 to ${LIMITS.eraYearsMax.toLocaleString()}.`;
    }
  }
  return null;
}

function orNull(value: string): string | null {
  const text = value.trim();
  return text === "" ? null : text;
}

/**
 * What the form sends. Every field is sent, so the same body creates an environment and (as a
 * patch) changes one.
 */
export function toEnvironmentIn(form: EnvironmentFormState): EnvironmentIn {
  return {
    name: form.name.trim(),
    description: form.description.trim(),
    era_kind: form.eraKind,
    era_years: form.eraKind === "present" ? null : wholeNumber(form.eraYears),
    era_setting: orNull(form.eraSetting),
    atmosphere: orNull(form.atmosphere),
    notes: orNull(form.notes),
  };
}
