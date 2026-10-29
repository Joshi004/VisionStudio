import { lazy, type ComponentType, type ReactNode } from "react";
import { Anchor, Stack, Text } from "@mantine/core";
import { Link } from "react-router";

import type { ProjectDetail } from "../../api/projects";

/** A named export of a module, loaded only when it is first rendered. */
function lazyNamed<K extends string, P extends object>(
  load: () => Promise<Record<K, ComponentType<P>>>,
  name: K,
) {
  return lazy(() => load().then((module) => ({ default: module[name] })));
}

const StoryEditor = lazyNamed(() => import("../story/StoryEditor"), "StoryEditor");
const CastPanel = lazyNamed(() => import("../story/CastPanel"), "CastPanel");
const ExplainerCastPanel = lazyNamed(
  () => import("../story/ExplainerCastPanel"),
  "ExplainerCastPanel",
);
const StoryPipelinePanel = lazyNamed(
  () => import("../story/StoryPipelinePanel"),
  "StoryPipelinePanel",
);
const StalenessPanel = lazyNamed(() => import("../story/StalenessPanel"), "StalenessPanel");
const StoryBiblePanel = lazyNamed(() => import("../story/StoryBiblePanel"), "StoryBiblePanel");
const DiscoveryPanel = lazyNamed(() => import("../story/DiscoveryPanel"), "DiscoveryPanel");
const ScenesPanel = lazyNamed(() => import("../story/ScenesPanel"), "ScenesPanel");
const CharacterLinksPanel = lazyNamed(
  () => import("../story/CharacterLinksPanel"),
  "CharacterLinksPanel",
);
const EnvironmentLinksPanel = lazyNamed(
  () => import("../story/EnvironmentLinksPanel"),
  "EnvironmentLinksPanel",
);
const CharacterRelationsPanel = lazyNamed(
  () => import("../story/CharacterRelationsPanel"),
  "CharacterRelationsPanel",
);
const CharacterDefinitionsPanel = lazyNamed(
  () => import("../story/CharacterDefinitionsPanel"),
  "CharacterDefinitionsPanel",
);
const CharacterImagesPanel = lazyNamed(
  () => import("../story/CharacterImagesPanel"),
  "CharacterImagesPanel",
);
const CharacterVoicesPanel = lazyNamed(
  () => import("../story/CharacterVoicesPanel"),
  "CharacterVoicesPanel",
);
const NarratorVoicePanel = lazyNamed(
  () => import("../story/NarratorVoicePanel"),
  "NarratorVoicePanel",
);
const EnvironmentDefinitionsPanel = lazyNamed(
  () => import("../story/EnvironmentDefinitionsPanel"),
  "EnvironmentDefinitionsPanel",
);
const EnvironmentViewsPanel = lazyNamed(
  () => import("../story/EnvironmentViewsPanel"),
  "EnvironmentViewsPanel",
);
const SceneDefinitionsPanel = lazyNamed(
  () => import("../story/SceneDefinitionsPanel"),
  "SceneDefinitionsPanel",
);
const SceneEventsPanel = lazyNamed(() => import("../story/SceneEventsPanel"), "SceneEventsPanel");
const LooksAndStatesPanel = lazyNamed(
  () => import("../story/LooksAndStatesPanel"),
  "LooksAndStatesPanel",
);
const SceneStagingPanel = lazyNamed(
  () => import("../story/SceneStagingPanel"),
  "SceneStagingPanel",
);
const LookStateImagesPanel = lazyNamed(
  () => import("../story/LookStateImagesPanel"),
  "LookStateImagesPanel",
);
const SpeechUnitsPanel = lazyNamed(() => import("../story/SpeechUnitsPanel"), "SpeechUnitsPanel");
const ShotPlansPanel = lazyNamed(() => import("../story/ShotPlansPanel"), "ShotPlansPanel");
const ShotDefinitionsPanel = lazyNamed(
  () => import("../story/ShotDefinitionsPanel"),
  "ShotDefinitionsPanel",
);
const ShotReferencesPanel = lazyNamed(
  () => import("../story/ShotReferencesPanel"),
  "ShotReferencesPanel",
);
const GenerationRequestsPanel = lazyNamed(
  () => import("../story/GenerationRequestsPanel"),
  "GenerationRequestsPanel",
);
const ShotPromptsPanel = lazyNamed(() => import("../story/ShotPromptsPanel"), "ShotPromptsPanel");
const ShotTakesPanel = lazyNamed(() => import("../story/ShotTakesPanel"), "ShotTakesPanel");
const StoryRenderPanel = lazyNamed(() => import("../story/StoryRenderPanel"), "StoryRenderPanel");
const MusicBiblePanel = lazyNamed(() => import("../music/MusicBiblePanel"), "MusicBiblePanel");
const MusicThemesPanel = lazyNamed(() => import("../music/MusicThemesPanel"), "MusicThemesPanel");
const MusicPlanPanel = lazyNamed(() => import("../music/MusicPlanPanel"), "MusicPlanPanel");
const CalloutPlanPanel = lazyNamed(() => import("../story/CalloutPlanPanel"), "CalloutPlanPanel");
const MusicCuesPanel = lazyNamed(() => import("../music/MusicCuesPanel"), "MusicCuesPanel");
const MusicTakesPanel = lazyNamed(() => import("../music/MusicTakesPanel"), "MusicTakesPanel");
const MusicPlacementPanel = lazyNamed(
  () => import("../music/MusicPlacementPanel"),
  "MusicPlacementPanel",
);

type StepPanelProps = {
  /** A pipeline step key, or one of the workspace keys (`WORKSPACE_ITEMS`). */
  stepKey: string;
  project: ProjectDetail;
};

/**
 * The existing stage panel for a step, the same one the classic page shows. Each panel is its
 * own chunk and makes its requests only once it is rendered here. It must be inside a
 * `Suspense`.
 */
export function StepPanel({ stepKey, project }: StepPanelProps) {
  const projectId = project.id;
  const hasStory = project.script_text !== null;

  function panelFor(): ReactNode {
    switch (stepKey) {
      case "story_text":
        return <StoryEditor project={project} />;
      case "cast":
        return project.kind === "explainer" ? (
          <ExplainerCastPanel projectId={projectId} />
        ) : (
          <CastPanel projectId={projectId} />
        );
      case "run":
        return <StoryPipelinePanel projectId={projectId} />;
      case "out_of_date":
        return <StalenessPanel projectId={projectId} />;
      case "story_bible":
        return <StoryBiblePanel projectId={projectId} hasStory={hasStory} />;
      case "character_discovery":
        return <DiscoveryPanel projectId={projectId} kind="characters" hasStory={hasStory} />;
      case "environment_discovery":
        return <DiscoveryPanel projectId={projectId} kind="environments" hasStory={hasStory} />;
      case "scene_discovery":
        return <ScenesPanel projectId={projectId} hasStory={hasStory} />;
      case "links":
        return (
          <Stack gap="md">
            <CharacterLinksPanel projectId={projectId} />
            <EnvironmentLinksPanel projectId={projectId} />
          </Stack>
        );
      case "relations":
        return <CharacterRelationsPanel projectId={projectId} />;
      case "character_definitions":
        return <CharacterDefinitionsPanel projectId={projectId} />;
      case "character_images":
        return <CharacterImagesPanel projectId={projectId} />;
      case "voices": {
        const dialogue = project.speech_mode !== "no_dialogue";
        const narrator = project.speech_mode !== "no_narration" && project.kind === "story";
        if (!dialogue && !narrator) {
          return <Text c="dimmed">This project's speech mode has no character or narrator voices.</Text>;
        }
        return (
          <Stack gap="md">
            {dialogue && <CharacterVoicesPanel projectId={projectId} />}
            {narrator && <NarratorVoicePanel projectId={projectId} />}
          </Stack>
        );
      }
      case "environment_definitions":
        return <EnvironmentDefinitionsPanel projectId={projectId} />;
      case "environment_views":
        return <EnvironmentViewsPanel projectId={projectId} />;
      case "scene_definitions":
        return <SceneDefinitionsPanel projectId={projectId} />;
      case "events":
        return <SceneEventsPanel projectId={projectId} speechMode={project.speech_mode} />;
      case "resolution":
        return <LooksAndStatesPanel projectId={projectId} />;
      case "scene_staging":
        return <SceneStagingPanel projectId={projectId} />;
      case "look_state_images":
        return <LookStateImagesPanel projectId={projectId} />;
      case "speech_units":
      case "speech_synthesis":
      case "word_timings":
        return <SpeechUnitsPanel projectId={projectId} />;
      case "callout_plan":
        return <CalloutPlanPanel projectId={projectId} />;
      case "music_bible":
        return <MusicBiblePanel projectId={projectId} hasStory={hasStory} />;
      case "music_themes":
        return <MusicThemesPanel projectId={projectId} />;
      case "music_plan":
        return <MusicPlanPanel projectId={projectId} />;
      case "music_cues":
        return <MusicCuesPanel projectId={projectId} />;
      case "music_generation":
        return <MusicTakesPanel projectId={projectId} />;
      case "music_placement":
        return <MusicPlacementPanel projectId={projectId} />;
      case "shot_plans":
        return <ShotPlansPanel projectId={projectId} />;
      case "shot_definitions":
      case "shot_continuity":
        return <ShotDefinitionsPanel projectId={projectId} />;
      case "references":
        return <ShotReferencesPanel projectId={projectId} />;
      case "generation_requests":
        return <GenerationRequestsPanel projectId={projectId} />;
      case "prompts":
        return <ShotPromptsPanel projectId={projectId} />;
      case "shot_generation":
        return <ShotTakesPanel projectId={projectId} />;
      case "render":
        return <StoryRenderPanel projectId={projectId} />;
      default:
        return (
          <Stack gap="xs" align="flex-start">
            <Text c="dimmed">No view for this step yet.</Text>
            <Anchor component={Link} to={`/projects/${projectId}/classic`} size="sm">
              Open the classic page
            </Anchor>
          </Stack>
        );
    }
  }

  return <>{panelFor()}</>;
}
