import { Alert, Anchor, Badge, Button, Grid, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError, describeError } from "../api/errors";
import { usePipelineBoard } from "../api/pipelineBoard";
import { isValidProjectId, useProject } from "../api/projects";
import { BoardHeader } from "../components/board/BoardHeader";
import { BoardStepDetail } from "../components/board/BoardStepDetail";
import { BoardStepList } from "../components/board/BoardStepList";
import { WORKSPACE_KEYS, stepPath } from "../components/board/boardSteps";
import { ProjectNotFound } from "../components/projects/ProjectNotFound";
import { capitalise } from "../format";

/**
 * The project's default page: every step of the pipeline at once, from one small request that
 * is made again only when the project's activity changes. The open step is in the address
 * (`/projects/:id/pipeline/:stepKey`); its panel is loaded only then.
 */
export function PipelineBoardPage() {
  const params = useParams();
  const navigate = useNavigate();
  const projectId = Number(params.projectId);
  const { data: project, isLoading, isError, error } = useProject(projectId);
  const board = usePipelineBoard(projectId);

  if (!isValidProjectId(projectId) || (error instanceof ApiError && error.status === 404)) {
    return <ProjectNotFound />;
  }

  // A key that is neither a step nor a project item opens nothing. Until the board is loaded
  // every key is trusted, so a link to a step does not wait for the board.
  const requestedKey = params.stepKey ?? null;
  const steps = board.data?.steps;
  const knownKey =
    requestedKey !== null &&
    (WORKSPACE_KEYS.has(requestedKey) ||
      steps === undefined ||
      steps.some((step) => step.key === requestedKey));
  const selectedKey = knownKey ? requestedKey : null;
  const selectedStep = steps?.find((step) => step.key === selectedKey);

  function openStep(key: string) {
    void navigate(stepPath(projectId, key));
  }

  return (
    <Stack gap="md">
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
            <Group gap="xs">
              <Button variant="default" component={Link} to={`/projects/${project.id}/classic`}>
                Classic view
              </Button>
              <Button variant="default" component={Link} to={`/projects/${project.id}/settings`}>
                Project settings
              </Button>
            </Group>
          </Group>

          {board.isError && (
            <Alert color="red" title="Could not load the pipeline board">
              {describeError(board.error)} Press Refresh to try again, or use the classic view.
            </Alert>
          )}
          {board.isLoading && <Loader size="sm" />}

          {board.data && (
            <>
              <BoardHeader projectId={project.id} board={board.data} onOpenStep={openStep} />
              <Grid gap="md">
                <Grid.Col span={{ base: 12, lg: 5, xl: 4 }}>
                  <div
                    style={{
                      position: "sticky",
                      top: 76,
                      maxHeight: "calc(100vh - 92px)",
                      overflowY: "auto",
                    }}
                  >
                    <BoardStepList
                      projectId={project.id}
                      board={board.data}
                      selectedKey={selectedKey}
                    />
                  </div>
                </Grid.Col>
                <Grid.Col span={{ base: 12, lg: 7, xl: 8 }}>
                  <BoardStepDetail project={project} stepKey={selectedKey} step={selectedStep} />
                </Grid.Col>
              </Grid>
            </>
          )}
        </>
      )}
    </Stack>
  );
}
