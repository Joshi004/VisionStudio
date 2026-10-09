import { Alert, Anchor, Badge, Button, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { Link, useParams } from "react-router";

import { ApiError, describeError } from "../api/errors";
import { isValidProjectId, useProject } from "../api/projects";
import { AutoPipelineSection } from "../components/projects/AutoPipelineSection";
import { RenderSection } from "../components/projects/RenderSection";
import { ScenesSection } from "../components/projects/ScenesSection";
import { ScriptSection } from "../components/projects/ScriptSection";
import { TranscriptSection } from "../components/projects/TranscriptSection";
import { VoiceoverSection } from "../components/projects/VoiceoverSection";
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
                Create your frames at {project.gen_width} x {project.gen_height}. The final video is{" "}
                {project.out_width} x {project.out_height} at {project.fps} fps.
              </Text>
            </Stack>
            <Button variant="default" component={Link} to={`/projects/${project.id}/settings`}>
              Project settings
            </Button>
          </Group>

          <VoiceoverSection project={project} />
          <ScriptSection project={project} />
          <AutoPipelineSection project={project} />
          <TranscriptSection project={project} />
          <ScenesSection project={project} />
          <RenderSection project={project} />
        </>
      )}
    </Stack>
  );
}
