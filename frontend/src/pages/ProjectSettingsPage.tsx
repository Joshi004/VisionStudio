import { Alert, Anchor, Loader, Stack, Title } from "@mantine/core";
import { Link, useParams } from "react-router";

import { ApiError, describeError } from "../api/errors";
import { isValidProjectId, useProject, useUpdateProject } from "../api/projects";
import { ProjectSettingsForm } from "../components/projects/ProjectSettingsForm";
import { settingsKey } from "../components/projects/settingsDraft";
import { ProjectNotFound } from "./ProjectPage";

export function ProjectSettingsPage() {
  const params = useParams();
  const projectId = Number(params.projectId);
  const { data: project, isLoading, isError, error } = useProject(projectId);
  const update = useUpdateProject(projectId);

  if (!isValidProjectId(projectId) || (error instanceof ApiError && error.status === 404)) {
    return <ProjectNotFound />;
  }

  return (
    <Stack gap="md" maw={820}>
      <Anchor component={Link} to={`/projects/${projectId}`} size="sm">
        ← Back to the project
      </Anchor>

      {isLoading && <Loader size="sm" />}

      {isError && (
        <Alert color="red" title="Could not load the project">
          {describeError(error)} Press Refresh to try again.
        </Alert>
      )}

      {project && (
        <>
          <Title order={2}>Settings: {project.name}</Title>
          <ProjectSettingsForm
            key={settingsKey(project)}
            project={project}
            isSaving={update.isPending}
            isSaved={update.isSuccess}
            error={update.isError ? describeError(update.error) : null}
            onEdit={update.reset}
            onSave={(changes) => update.mutate(changes)}
          />
        </>
      )}
    </Stack>
  );
}
