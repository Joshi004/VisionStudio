/** The agent's addresses are shown as links only when they are plain http or https. */
export function safeHref(value: string | null): string | null {
  return value !== null && /^https?:\/\//i.test(value) ? value : null;
}
