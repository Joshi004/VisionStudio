// The motion of the templates (§4.5.1, "The look rules"): when a part enters, how it eases, and
// how a number counts up. Everything depends only on the frame number, so two renders of the
// same input are identical.

// Frames an element takes to arrive, for each `motion` of the theme.
const DURATION: Record<string, number> = { snappy: 12, smooth: 18, calm: 24 };

export function durationOf(motion: string): number {
  return DURATION[motion] ?? 12;
}

// Ease-out cubic: `1 - (1 - t)^3`.
export function ease(t: number): number {
  return 1 - (1 - t) ** 3;
}

// How far an element that enters on `beatFrame` has come at `frame`, from 0 to 1, eased. It is 0
// on the frame before its beat, already above 0 on the beat's frame, and 1 `duration - 1` frames
// after it.
export function progressAt(frame: number, beatFrame: number, motion: string): number {
  const t = (frame - beatFrame + 1) / durationOf(motion);
  return ease(Math.min(1, Math.max(0, t)));
}

// sign, dollar sign, digits (with commas and decimals), K/M/B/T, suffix: the forms `display_text`
// of the backend writes.
const NUMBER = /^([+-]?)(\$?)(\d[\d,]*(?:\.\d+)?)([KMBT]?)(%| pts|x)?$/;

function withCommas(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

// The text of a number that is counting up: only its digits count, from 0 up to the target with
// the target's decimals. The sign, the dollar sign, the letter and the suffix stay as they are.
// At the end (and for a text that is not a number) it is `display` exactly.
export function countedText(display: string, progress: number, count: boolean): string {
  if (!count || progress >= 1) return display;
  const match = NUMBER.exec(display);
  if (match === null) return display;
  const [, sign = "", dollar = "", digits = "", letter = "", suffix = ""] = match;
  const places = digits.includes(".") ? digits.length - digits.indexOf(".") - 1 : 0;
  const target = Number(digits.replaceAll(",", ""));
  const scale = 10 ** places;
  const shown = (Math.round(target * progress * scale) / scale).toFixed(places);
  const [whole = "0", fraction] = shown.split(".");
  const grouped = digits.includes(",") ? withCommas(whole) : whole;
  const body = fraction === undefined ? grouped : `${grouped}.${fraction}`;
  return `${sign}${dollar}${body}${letter}${suffix}`;
}
