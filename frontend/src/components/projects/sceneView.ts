import type { Proposal, ScenesState } from "../../api/scenes";

type StaleReason = ScenesState["stale_reasons"][number];

const STALE_MESSAGES: Record<StaleReason, string> = {
  script_changed: "The script has changed since these scenes were proposed.",
  voiceover_changed: "The voiceover has changed since these scenes were proposed.",
};

export function staleSceneMessage(reason: StaleReason): string {
  return STALE_MESSAGES[reason];
}

// Times are stored with 3 decimals, so a length this close to a limit counts as on it.
const LIMIT_TOLERANCE_S = 0.001;

/** True when a scene is shorter than the minimum or longer than the maximum. */
export function isOutsideLimits(lengthS: number, minS: number, maxS: number): boolean {
  return lengthS < minS - LIMIT_TOLERANCE_S || lengthS > maxS + LIMIT_TOLERANCE_S;
}

/** "3.28" for a time or a length in seconds. */
export function seconds(value: number): string {
  return value.toFixed(2);
}

/** The host (and port) of the address the model will be called at, for the paid-call notice. */
export function llmHost(willCall: string | null): string {
  if (!willCall) {
    return "the language model's address";
  }
  try {
    return new URL(willCall).host;
  } catch {
    return willCall;
  }
}

/** "zai-org/GLM-5.3-Flash · 1,492 prompt + 2,242 output tokens (1,792 reasoning)". */
export function usageLine(proposal: Proposal): string | null {
  const { usage } = proposal;
  if (!usage || usage.prompt_tokens === null || usage.completion_tokens === null) {
    return null;
  }
  const parts = [
    `${usage.prompt_tokens.toLocaleString()} prompt + ${usage.completion_tokens.toLocaleString()} output tokens`,
  ];
  if (usage.reasoning_tokens !== null) {
    parts[0] += ` (${usage.reasoning_tokens.toLocaleString()} reasoning)`;
  }
  return proposal.model ? `${proposal.model} · ${parts[0]}` : parts[0];
}

/** What the checks and the splitter did to the model's cuts, in one line. */
export function checksLine(proposal: Proposal): string | null {
  const { checks, splitter } = proposal;
  if (proposal.source === "rule" || !checks) {
    return null;
  }
  const parts = [
    `${checks.exact} of ${checks.entries} cuts matched their checksum words`,
    `${checks.moved} moved`,
    `${checks.flagged} flagged`,
  ];
  if (checks.dropped > 0) {
    parts.push(`${checks.dropped} unusable`);
  }
  let line = parts.join(" · ");
  if (splitter && (splitter.cuts_added > 0 || splitter.cuts_removed > 0)) {
    line += ` · the splitter added ${splitter.cuts_added} and removed ${splitter.cuts_removed} to fit the limits`;
  }
  return line;
}
