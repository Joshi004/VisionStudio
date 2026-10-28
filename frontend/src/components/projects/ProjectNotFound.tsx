import { Button, Stack, Text, Title } from "@mantine/core";
import { Link } from "react-router";

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
