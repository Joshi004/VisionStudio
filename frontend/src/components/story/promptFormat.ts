import type { JobPrompt } from "../../api/prompts";

/** One text of a prompt that the drawer shows under its own tab. */
export type PromptTab = { id: string; label: string; text: string };

/** The start of a text, cut at a whole word and marked when something was left out. */
export function excerpt(text: string, max: number): string {
  const flat = text.trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()} …`;
}

// A data block of a stage's request starts with a heading of capitals on its own line:
// "SHOT (JSON):", "STORY:", "USER FEEDBACK (plain text from the user):".
const BLOCK_HEADING = /^([A-Z][A-Z0-9 ,'’/-]{2,60}?)(?: \([^)\n]{1,40}\))?:$/gm;

/** The names of the data blocks a request's user message is made of, in order. */
export function blockTitles(userMessage: string): string[] {
  const titles: string[] = [];
  for (const match of userMessage.matchAll(BLOCK_HEADING)) {
    const title = match[1].trim();
    if (!titles.includes(title)) titles.push(title);
  }
  return titles.slice(0, 14);
}

function role(prompt: JobPrompt, name: string): string {
  return prompt.messages
    .filter((message) => message.role === name)
    .map((message) => message.content)
    .join("\n\n");
}

/** The system message (the instructions) of a language-model request. */
export function instructionsOf(prompt: JobPrompt): string {
  return role(prompt, "system");
}

/** The user message (the data the stage sent) of a language-model request. */
export function inputOf(prompt: JobPrompt): string {
  return role(prompt, "user");
}

function answerText(prompt: JobPrompt): string {
  if (prompt.answer !== null && prompt.answer !== undefined) {
    return JSON.stringify(prompt.answer, null, 2);
  }
  if (prompt.unusable_answer) {
    return `No answer could be used. The last one the model gave:\n\n${prompt.unusable_answer}`;
  }
  return "The model has not answered.";
}

/** The tabs of the drawer for a job's prompt. */
export function jobPromptTabs(prompt: JobPrompt): PromptTab[] {
  if (prompt.kind === "llm") {
    return [
      { id: "instructions", label: "Instructions", text: instructionsOf(prompt) },
      { id: "input", label: "Input", text: inputOf(prompt) },
      { id: "answer", label: "Answer", text: answerText(prompt) },
    ];
  }
  if (prompt.media) {
    return [{ id: "prompt", label: "Prompt", text: prompt.media.prompt }];
  }
  return [];
}

/** Short facts about a job's request, one per entry: the model, the numbers, the files. */
export function jobPromptFacts(prompt: JobPrompt): string[] {
  const facts: string[] = [];
  if (prompt.model) facts.push(`Model ${prompt.model}`);
  for (const [key, value] of Object.entries(prompt.settings)) {
    facts.push(`${key.replaceAll("_", " ")} ${String(value)}`);
  }
  const media = prompt.media;
  if (media) {
    if (media.endpoint) facts.push(media.endpoint);
    if (media.seed !== null) facts.push(`seed ${media.seed}`);
    if (media.num_frames !== null) facts.push(`${media.num_frames} frames`);
    if (media.width !== null && media.height !== null) {
      facts.push(`${media.width}x${media.height}`);
    }
    if (media.pictures > 0) facts.push(`${media.pictures} pictures`);
    if (media.audios > 0) facts.push(`${media.audios} audios`);
  }
  return facts;
}
