import { isJobActive } from "../../api/polling";
import type { Cast, CastMember } from "../../api/cast";

/** The status of a member's reference, as the page words it. */
const STATUS_TEXT: Record<CastMember["status"], string> = {
  pending: "Nothing yet",
  prompted: "Prompt written",
  ready: "Picture ready",
  failed: "Picture failed",
};

const STATUS_COLOR: Record<CastMember["status"], string> = {
  pending: "gray",
  prompted: "blue",
  ready: "green",
  failed: "red",
};

export function memberStatusText(member: CastMember): string {
  return STATUS_TEXT[member.status];
}

export function memberStatusColor(member: CastMember): string {
  return STATUS_COLOR[member.status];
}

/** A prompt or a picture is being made for the member now. */
export function memberIsBusy(member: CastMember): boolean {
  return isJobActive(member.prompt_job) || isJobActive(member.image_job);
}

/** How many members have a picture, of how many there are: "2 of 5 pictures made". */
export function pictureCountsLine(cast: Cast): string {
  const members = [...cast.characters, ...cast.locations];
  const ready = members.filter((member) => member.reference_url !== null).length;
  return `${ready} of ${members.length} ${members.length === 1 ? "picture" : "pictures"} made`;
}

/** "3 of 8 scenes have a choice of characters and place", or an empty text with no scenes. */
export function assignedLine(cast: Cast): string {
  if (cast.scene_count === 0) {
    return "There are no scenes yet.";
  }
  return `${cast.scenes_assigned} of ${cast.scene_count} ${
    cast.scene_count === 1 ? "scene has" : "scenes have"
  } a choice of characters and place.`;
}
