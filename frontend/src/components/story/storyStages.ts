export type StoryStage = {
  id: string;
  name: string;
  description: string;
  /** True once the stage can be run from the story workspace. Missing means "not yet". */
  available?: boolean;
};

/**
 * The pipeline's stages in order (Path_ahead.md, Stages 1 to 19). None can run yet: each later
 * phase replaces its placeholder in `StageList` with real controls.
 */
export const STORY_STAGES: readonly StoryStage[] = [
  {
    id: "story-bible",
    name: "Story Bible",
    description: "The story's world, tone and rules, written once and shared by every later stage.",
    available: true,
  },
  {
    id: "character-discovery",
    name: "Character discovery",
    description: "Finds the characters the story needs.",
    available: true,
  },
  {
    id: "environment-discovery",
    name: "Environment discovery",
    description: "Finds the places the story happens in.",
    available: true,
  },
  {
    id: "scene-discovery",
    name: "Scene discovery",
    description: "Splits the story into scenes, each one a slice of the original text.",
    available: true,
  },
  {
    id: "character-relations",
    name: "Character relations",
    description:
      "Finds who is the same person at another age, who is a twin, and who is family, so they look alike.",
    available: true,
  },
  {
    id: "character-definitions",
    name: "Character definitions",
    description: "Describes each character in detail and gives them a look and a voice.",
    available: true,
  },
  {
    id: "environment-definitions",
    name: "Environment definitions",
    description: "Describes and illustrates each place.",
    available: true,
  },
  {
    id: "scene-definitions",
    name: "Scene definitions",
    description: "Decides where and when each scene happens and who is in it.",
    available: true,
  },
  {
    id: "event-extraction",
    name: "Event extraction",
    description: "Lists what happens in each scene: narration, dialogue, actions and sounds.",
    available: true,
  },
  {
    id: "looks-and-states",
    name: "Looks and environment states",
    description:
      "Settles which outfits and conditions (such as night) the scenes need, then draws the new ones from the canonical pictures.",
    available: true,
  },
  {
    id: "speech-planning",
    name: "Speech planning",
    description: "Cuts spoken text into short units that can each be turned into speech.",
    available: true,
  },
  {
    id: "speech-synthesis",
    name: "Speech synthesis",
    description: "Turns each speech unit into audio in the right voice.",
    available: true,
  },
  {
    id: "shot-planning",
    name: "Shot planning",
    description: "Plans the shots of each scene against the real length of the speech.",
    available: true,
  },
  {
    id: "shot-definitions",
    name: "Shot definitions",
    description: "Describes each shot in detail: framing, action and continuity.",
    available: true,
  },
  {
    id: "reference-selection",
    name: "Reference selection",
    description: "Chooses the pictures and voices each shot is generated from.",
    available: true,
  },
  {
    id: "generation-planning",
    name: "Generation planning",
    description: "Decides how each shot is requested from the video model.",
    available: true,
  },
  {
    id: "h3-prompts",
    name: "H3 prompts",
    description: "Writes the final prompt for each shot.",
    available: true,
  },
  {
    id: "shot-generation",
    name: "Shot generation",
    description: "Makes each shot's video clip.",
  },
  {
    id: "final-render",
    name: "Final render",
    description: "Joins the shots on one timeline into the finished video.",
  },
];
