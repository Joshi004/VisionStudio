import type { SceneEvent } from "../../api/sceneEvents";
import type { Shot } from "../../api/shotPlans";
import type { SpeechUnit } from "../../api/speechUnits";

/** How a shot's type is shown: its label and badge colour. */
export const SHOT_TYPE: Record<Shot["type"], { label: string; color: string }> =
  {
    establishing: { label: "Establishing", color: "indigo" },
    action: { label: "Action", color: "grape" },
    reaction: { label: "Reaction", color: "pink" },
    dialogue: { label: "Dialogue", color: "teal" },
    insert: { label: "Insert", color: "orange" },
    transition: { label: "Transition", color: "gray" },
    // A continuous explainer's shot that shows the presenter; only the cut planner writes it.
    presenter: { label: "Presenter", color: "cyan" },
  };

/** The shot types a person may choose when editing a shot. `presenter` is only ever written by
 * the cut planning of a continuous explainer, which cannot be edited by hand.
 */
export const SHOT_TYPES = Object.keys(SHOT_TYPE).filter(
  (type) => type !== "presenter",
) as Shot["type"][];

const EVENT_LABEL: Record<SceneEvent["type"], string> = {
  narration: "Narration",
  dialogue: "Dialogue",
  action: "Action",
  sound_event: "Sound",
  pause: "Pause",
};

export function shorten(text: string, limit = 70): string {
  return text.length <= limit ? text : `${text.slice(0, limit).trimEnd()}...`;
}

export function seconds(value: number): string {
  // Two decimals: a shot's length is one of H3's own, such as 2.33 or 3.04 s.
  return `${value.toFixed(2)} s`;
}

/** One line about an event: its kind, who speaks it, and the start of its words. */
export function eventText(
  event: SceneEvent,
  characterNames: Record<string, string>,
): string {
  const body = event.text ?? event.description ?? "";
  const speaker =
    event.speaker_id != null
      ? (characterNames[event.speaker_id] ?? event.speaker_id)
      : null;
  const label = EVENT_LABEL[event.type];
  const prefix = speaker !== null ? `${label}, ${speaker}` : label;
  return body === "" ? prefix : `${prefix}: ${shorten(body)}`;
}

/** One line about a speech unit: who says it, and the start of its words. */
export function unitText(
  unit: SpeechUnit,
  characterNames: Record<string, string>,
): string {
  const speaker =
    unit.speaker_id != null
      ? (characterNames[unit.speaker_id] ?? unit.speaker_id)
      : "Narrator";
  return `${speaker}: ${shorten(unit.text)}`;
}
