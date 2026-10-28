import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { Link, useParams } from "react-router";

import { ApiError, describeError } from "../api/errors";
import { isValidProjectId, useProject } from "../api/projects";
import { ProjectNotFound } from "../components/projects/ProjectNotFound";
import { CastPanel } from "../components/story/CastPanel";
import { CollapsiblePanel } from "../components/story/CollapsiblePanel";
import {
  ProjectPanelsContext,
  useOpenPanels,
} from "../components/story/projectPanels";
import { CharacterDefinitionsPanel } from "../components/story/CharacterDefinitionsPanel";
import { CharacterImagesPanel } from "../components/story/CharacterImagesPanel";
import { CharacterLinksPanel } from "../components/story/CharacterLinksPanel";
import { CharacterRelationsPanel } from "../components/story/CharacterRelationsPanel";
import { CharacterVoicesPanel } from "../components/story/CharacterVoicesPanel";
import { DiscoveryPanel } from "../components/story/DiscoveryPanel";
import { EnvironmentDefinitionsPanel } from "../components/story/EnvironmentDefinitionsPanel";
import { EnvironmentLinksPanel } from "../components/story/EnvironmentLinksPanel";
import { ExplainerCastPanel } from "../components/story/ExplainerCastPanel";
import { LookStateImagesPanel } from "../components/story/LookStateImagesPanel";
import { LooksAndStatesPanel } from "../components/story/LooksAndStatesPanel";
import { NarratorVoicePanel } from "../components/story/NarratorVoicePanel";
import { SceneDefinitionsPanel } from "../components/story/SceneDefinitionsPanel";
import { EnvironmentViewsPanel } from "../components/story/EnvironmentViewsPanel";
import { SceneEventsPanel } from "../components/story/SceneEventsPanel";
import { MusicBiblePanel } from "../components/music/MusicBiblePanel";
import { MusicCuesPanel } from "../components/music/MusicCuesPanel";
import { MusicPlacementPanel } from "../components/music/MusicPlacementPanel";
import { MusicPlanPanel } from "../components/music/MusicPlanPanel";
import { MusicTakesPanel } from "../components/music/MusicTakesPanel";
import { MusicThemesPanel } from "../components/music/MusicThemesPanel";
import { SceneStagingPanel } from "../components/story/SceneStagingPanel";
import { ScenesPanel } from "../components/story/ScenesPanel";
import { GenerationRequestsPanel } from "../components/story/GenerationRequestsPanel";
import { ShotDefinitionsPanel } from "../components/story/ShotDefinitionsPanel";
import { ShotPlansPanel } from "../components/story/ShotPlansPanel";
import { ShotPromptsPanel } from "../components/story/ShotPromptsPanel";
import { ShotReferencesPanel } from "../components/story/ShotReferencesPanel";
import { ShotTakesPanel } from "../components/story/ShotTakesPanel";
import { StoryRenderPanel } from "../components/story/StoryRenderPanel";
import { SpeechUnitsPanel } from "../components/story/SpeechUnitsPanel";
import { StageList } from "../components/story/StageList";
import { StalenessPanel } from "../components/story/StalenessPanel";
import { StoryBiblePanel } from "../components/story/StoryBiblePanel";
import { StoryEditor } from "../components/story/StoryEditor";
import { StoryPipelinePanel } from "../components/story/StoryPipelinePanel";
import { capitalise } from "../format";

export function ProjectPage() {
  const params = useParams();
  const projectId = Number(params.projectId);
  const { data: project, isLoading, isError, error } = useProject(projectId);
  const panels = useOpenPanels(projectId);

  if (
    !isValidProjectId(projectId) ||
    (error instanceof ApiError && error.status === 404)
  ) {
    return <ProjectNotFound />;
  }

  return (
    <ProjectPanelsContext.Provider value={panels}>
    <Stack gap="md" maw={820}>
      <Anchor component={Link} to="/projects" size="sm">
        ← All projects
      </Anchor>

      {isLoading && <Loader size="sm" />}

      {isError && (
        <Alert color="red" title="Could not load the project">
          {describeError(error)} Press Refresh to try again.
        </Alert>
      )}

      {project && (
        <>
          <Group justify="space-between" align="flex-start">
            <Stack gap={4}>
              <Group gap="sm">
                <Title order={2}>{project.name}</Title>
                <Badge variant="light">{capitalise(project.orientation)}</Badge>
              </Group>
              <Text size="sm" c="dimmed">
                Generation size {project.gen_width} x {project.gen_height}. The
                final video is {project.out_width} x {project.out_height} at{" "}
                {project.fps} fps.
              </Text>
            </Stack>
            <Group gap="xs">
              <Button variant="default" component={Link} to={`/projects/${project.id}`}>
                Pipeline board
              </Button>
              <Button
                variant="default"
                component={Link}
                to={`/projects/${project.id}/settings`}
              >
                Project settings
              </Button>
            </Group>
          </Group>

          <StoryEditor project={project} />
          {project.kind === "explainer" ? (
            <CollapsiblePanel panelKey="cast" title="Presenter and set">
              <ExplainerCastPanel projectId={project.id} />
            </CollapsiblePanel>
          ) : (
            <CollapsiblePanel panelKey="cast" title="Cast">
              <CastPanel projectId={project.id} />
            </CollapsiblePanel>
          )}
          <StoryPipelinePanel projectId={project.id} />
          <CollapsiblePanel panelKey="staleness" title="What is out of date">
            <StalenessPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="story_bible" title="Story Bible">
            <StoryBiblePanel
              projectId={project.id}
              hasStory={project.script_text !== null}
            />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="character_discovery"
            anchorId="pipeline-step-character_discovery"
            title="Characters"
          >
            <DiscoveryPanel
              projectId={project.id}
              kind="characters"
              hasStory={project.script_text !== null}
            />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="character_links" title="Library links">
            <CharacterLinksPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="character_relations" title="Character relations">
            <CharacterRelationsPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="character_definitions" title="Character definitions">
            <CharacterDefinitionsPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="character_images"
            anchorId="pipeline-step-character_images"
            title="Character images"
          >
            <CharacterImagesPanel projectId={project.id} />
          </CollapsiblePanel>
          {project.speech_mode !== "no_dialogue" && (
            <CollapsiblePanel panelKey="character_voices" title="Character voices">
              <CharacterVoicesPanel projectId={project.id} />
            </CollapsiblePanel>
          )}
          {project.speech_mode !== "no_narration" && project.kind === "story" && (
            <CollapsiblePanel panelKey="narrator_voice" title="Narrator voice">
              <NarratorVoicePanel projectId={project.id} />
            </CollapsiblePanel>
          )}
          <CollapsiblePanel
            panelKey="environment_discovery"
            anchorId="pipeline-step-environment_discovery"
            title="Environments"
          >
            <DiscoveryPanel
              projectId={project.id}
              kind="environments"
              hasStory={project.script_text !== null}
            />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="environment_links" title="Environment library links">
            <EnvironmentLinksPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="scene_discovery"
            anchorId="pipeline-step-scene_discovery"
            title="Scenes"
          >
            <ScenesPanel
              projectId={project.id}
              hasStory={project.script_text !== null}
            />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="environment_definitions"
            anchorId="pipeline-step-environment_definitions"
            title="Environment definitions"
          >
            <EnvironmentDefinitionsPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="scene_definitions"
            anchorId="pipeline-step-scene_definitions"
            title="Scene definitions"
          >
            <SceneDefinitionsPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="events"
            anchorId="pipeline-step-events"
            title="Scene events"
          >
            <SceneEventsPanel
              projectId={project.id}
              speechMode={project.speech_mode}
            />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="music_bible"
            anchorId="pipeline-step-music_bible"
            title="Music Bible"
          >
            <MusicBiblePanel
              projectId={project.id}
              hasStory={project.script_text !== null}
            />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="music_themes"
            anchorId="pipeline-step-music_themes"
            title="Music themes"
          >
            <MusicThemesPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="scene_staging"
            anchorId="pipeline-step-scene_staging"
            title="Scene staging"
          >
            <SceneStagingPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="environment_views"
            anchorId="pipeline-step-environment_views"
            title="Environment views"
          >
            <EnvironmentViewsPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="looks_and_states" title="Looks and environment states">
            <LooksAndStatesPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="look_state_images" title="New looks and states: pictures">
            <LookStateImagesPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="speech_units" title="Speech units">
            <SpeechUnitsPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="shot_plans"
            anchorId="pipeline-step-shot_plans"
            title="Shot plans"
          >
            <ShotPlansPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="music_plan"
            anchorId="pipeline-step-music_plan"
            title="Music plan"
          >
            <MusicPlanPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="shot_definitions" title="Shot definitions">
            <ShotDefinitionsPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="music_cues"
            anchorId="pipeline-step-music_cues"
            title="Music cues"
          >
            <MusicCuesPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="music_generation"
            anchorId="pipeline-step-music_generation"
            title="Music takes"
          >
            <MusicTakesPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="shot_references" title="Shot references">
            <ShotReferencesPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="generation_requests" title="Generation planning">
            <GenerationRequestsPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="shot_prompts" title="H3 prompts">
            <ShotPromptsPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="shot_generation"
            anchorId="pipeline-step-shot_generation"
            title="Shot generation"
          >
            <ShotTakesPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel
            panelKey="music_placement"
            anchorId="pipeline-step-music_placement"
            title="Music placement"
          >
            <MusicPlacementPanel projectId={project.id} />
          </CollapsiblePanel>
          <CollapsiblePanel panelKey="story_render" title="Final render">
            <StoryRenderPanel projectId={project.id} />
          </CollapsiblePanel>
          <StageList />
        </>
      )}
    </Stack>
    </ProjectPanelsContext.Provider>
  );
}
