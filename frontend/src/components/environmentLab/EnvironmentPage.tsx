import {
  Alert,
  Badge,
  Button,
  Grid,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { useEditEnvironment, useLibraryEnvironment } from "../../api/environmentLab";
import { describeError } from "../../api/errors";
import { EnvironmentVersionHistory } from "./EnvironmentVersionHistory";
import { eraText } from "./environmentLabView";
import { ReferencePicker } from "./ReferencePicker";

type EnvironmentPageProps = {
  environmentId: number;
  onBack: () => void;
  /** Opens the drawer to edit the profile. */
  onEdit: () => void;
};

function Detail({ label, value }: { label: string; value: string | null }) {
  if (value === null || value.trim() === "") {
    return null;
  }
  return (
    <Text size="sm">
      <Text span fw={500}>
        {label}:{" "}
      </Text>
      {value}
    </Text>
  );
}

/**
 * One environment: its profile and the version history on the left; on the right, its
 * canonical picture and the pictures being made for it. The profile is changed in the drawer.
 */
export function EnvironmentPage({ environmentId, onBack, onEdit }: EnvironmentPageProps) {
  const environment = useLibraryEnvironment(environmentId);
  const edit = useEditEnvironment();

  const back = (
    <Group>
      <Button variant="subtle" size="compact-sm" onClick={onBack}>
        Back to the environments
      </Button>
    </Group>
  );

  if (environment.isLoading) {
    return (
      <Stack gap="md">
        {back}
        <Loader size="sm" />
      </Stack>
    );
  }
  if (environment.isError || !environment.data) {
    return (
      <Stack gap="md">
        {back}
        <Alert color="red" title="Could not open the environment">
          {describeError(environment.error)}
        </Alert>
      </Stack>
    );
  }

  const data = environment.data;

  return (
    <Stack gap="md">
      {back}
      <Grid gap="lg">
        <Grid.Col span={{ base: 12, lg: 5 }}>
          <Paper withBorder p="md" radius="md">
            <Stack gap="md">
              <Stack gap={4}>
                <Group gap="xs" align="center">
                  <Title order={3}>{data.name}</Title>
                  {data.version !== null && (
                    <Badge variant="light" color="blue" title="The newest version of this environment">
                      v{data.version}
                    </Badge>
                  )}
                  {data.archived && (
                    <Badge variant="light" color="orange">
                      archived
                    </Badge>
                  )}
                </Group>
                <Text size="sm" c="dimmed">
                  {eraText(data)}
                </Text>
              </Stack>

              <Group gap="xs">
                <Button size="compact-sm" variant="default" onClick={onEdit}>
                  Edit
                </Button>
                <Button
                  size="compact-sm"
                  variant="subtle"
                  color="orange"
                  loading={edit.isPending}
                  onClick={() =>
                    edit.mutate({ environmentId: data.id, body: { archived: !data.archived } })
                  }
                >
                  {data.archived ? "Unarchive" : "Archive"}
                </Button>
              </Group>
              {edit.isError && (
                <Alert color="red" p="xs">
                  {describeError(edit.error)}
                </Alert>
              )}

              <Stack gap={4}>
                <Detail label="Description" value={data.description} />
                <Detail label="Atmosphere" value={data.atmosphere} />
                <Detail label="Notes" value={data.notes} />
              </Stack>

              <EnvironmentVersionHistory environmentId={data.id} />
            </Stack>
          </Paper>
        </Grid.Col>

        <Grid.Col span={{ base: 12, lg: 7 }}>
          <Stack gap="lg">
            <Paper withBorder p="md" radius="md">
              <Stack gap="xs">
                <Text size="sm" fw={600}>
                  Canonical picture{data.version !== null ? ` (version ${data.version})` : ""}
                </Text>
                {data.image !== null ? (
                  <img
                    src={data.image.url}
                    alt={`${data.name}, reference picture`}
                    style={{
                      width: "100%",
                      aspectRatio: "16 / 9",
                      objectFit: "cover",
                      borderRadius: 4,
                      display: "block",
                    }}
                  />
                ) : (
                  <Text size="sm" c="dimmed">
                    No picture for this version yet. Press Make the picture.
                  </Text>
                )}
              </Stack>
            </Paper>
            <Paper withBorder p="md" radius="md">
              <ReferencePicker environment={data} />
            </Paper>
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
