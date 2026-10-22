import { Alert, Anchor, Badge, Button, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { Link, useParams } from "react-router";

import { ApiError, describeError } from "../api/errors";
import { isValidProjectId, useProject } from "../api/projects";
import { CastPanel } from "../components/story/CastPanel";
import { CharacterDefinitionsPanel } from "../components/story/CharacterDefinitionsPanel";
import { CharacterImagesPanel } from "../components/story/CharacterImagesPanel";
import { CharacterLinksPanel } from "../components/story/CharacterLinksPanel";
import { CharacterRelationsPanel } from "../components/story/CharacterRelationsPanel";
import { CharacterVoicesPanel } from "../components/story/CharacterVoicesPanel";
import { DiscoveryPanel } from "../components/story/DiscoveryPanel";
import { EnvironmentDefinitionsPanel } from "../components/story/EnvironmentDefinitionsPanel";
import { EnvironmentLinksPanel } from "../components/story/EnvironmentLinksPanel";
import { LookStateImagesPanel } from "../components/story/LookStateImagesPanel";
import { LooksAndStatesPanel } from "../components/story/LooksAndStatesPanel";
import { NarratorVoicePanel } from "../components/story/NarratorVoicePanel";
import { SceneDefinitionsPanel } from "../components/story/SceneDefinitionsPanel";
import { SceneEventsPanel } from "../components/story/SceneEventsPanel";
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
import { StoryBiblePanel } from "../components/story/StoryBiblePanel";
import { StoryEditor } from "../components/story/StoryEditor";
import { StoryPipelinePanel } from "../components/story/StoryPipelinePanel";
import { capitalise } from "../format";

export function ProjectNotFound() {
  return (
    <Stack align="flex-start" gap="sm">
      <Title order={2}>Project not found</Title>
      <Text c="dimmed">This project does not exist.</Text>
      <Button component={Link} to="/projects">
        Back to Projects
      </Button>
    </Stack>
  );
}

export function ProjectPage() {
  const params = useParams();
  const projectId = Number(params.projectId);
  const { data: project, isLoading, isError, error } = useProject(projectId);

  if (!isValidProjectId(projectId) || (error instanceof ApiError && error.status === 404)) {
    return <ProjectNotFound />;
  }

  return (
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
                Generation size {project.gen_width} x {project.gen_height}. The final video is{" "}
                {project.out_width} x {project.out_height} at {project.fps} fps.
              </Text>
            </Stack>
            <Button variant="default" component={Link} to={`/projects/${project.id}/settings`}>
              Project settings
            </Button>
          </Group>

          <StoryEditor project={project} />
          <CastPanel projectId={project.id} />
          <StoryPipelinePanel projectId={project.id} />
          <StoryBiblePanel projectId={project.id} hasStory={project.script_text !== null} />
          <DiscoveryPanel
            projectId={project.id}
            kind="characters"
            hasStory={project.script_text !== null}
          />
          <CharacterLinksPanel projectId={project.id} />
          <CharacterRelationsPanel projectId={project.id} />
          <CharacterDefinitionsPanel projectId={project.id} />
          <CharacterImagesPanel projectId={project.id} />
          <CharacterVoicesPanel projectId={project.id} />
          <NarratorVoicePanel projectId={project.id} />
          <DiscoveryPanel
            projectId={project.id}
            kind="environments"
            hasStory={project.script_text !== null}
          />
          <EnvironmentLinksPanel projectId={project.id} />
          <ScenesPanel projectId={project.id} hasStory={project.script_text !== null} />
          <EnvironmentDefinitionsPanel projectId={project.id} />
          <SceneDefinitionsPanel projectId={project.id} />
          <SceneEventsPanel projectId={project.id} />
          <LooksAndStatesPanel projectId={project.id} />
          <LookStateImagesPanel projectId={project.id} />
          <SpeechUnitsPanel projectId={project.id} />
          <ShotPlansPanel projectId={project.id} />
          <ShotDefinitionsPanel projectId={project.id} />
          <ShotReferencesPanel projectId={project.id} />
          <GenerationRequestsPanel projectId={project.id} />
          <ShotPromptsPanel projectId={project.id} />
          <ShotTakesPanel projectId={project.id} />
          <StoryRenderPanel projectId={project.id} />
          <StageList />
        </>
      )}
    </Stack>
  );
}
