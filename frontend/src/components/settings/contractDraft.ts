import type { ContractSourceIn, ContractSources } from "../../api/gpu";

export const MAX_SOURCES = 5;

export type SourceBase = "gpu" | "transcription";

export const BASE_OPTIONS: { value: SourceBase; label: string }[] = [
  { value: "gpu", label: "GPU server URL" },
  { value: "transcription", label: "Transcription URL" },
];

export type SourceDraft = {
  /** Only for React's list key. It is not sent. */
  id: number;
  name: string;
  base: SourceBase;
  path: string;
};

let lastId = 0;

function nextId(): number {
  lastId += 1;
  return lastId;
}

export function newSourceDraft(): SourceDraft {
  return { id: nextId(), name: "", base: "gpu", path: "/" };
}

export function toDraft(saved: ContractSources): SourceDraft[] {
  return saved.sources.map((item) => ({
    id: nextId(),
    name: item.name,
    base: item.base,
    path: item.path,
  }));
}

export function toRequest(draft: SourceDraft[]): ContractSourceIn[] {
  return draft.map(({ name, base, path }) => ({ name, base, path }));
}

export function isUnchanged(draft: SourceDraft[], saved: ContractSources): boolean {
  return (
    draft.length === saved.sources.length &&
    draft.every((item, index) => {
      const original = saved.sources[index];
      return (
        item.name === original.name && item.base === original.base && item.path === original.path
      );
    })
  );
}
