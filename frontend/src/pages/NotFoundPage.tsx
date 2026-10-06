import { Button, Stack, Text, Title } from "@mantine/core";
import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <Stack align="center" gap="sm" py="xl">
      <Title order={2}>Not found</Title>
      <Text c="dimmed">This page does not exist.</Text>
      <Button component={Link} to="/projects">
        Go to Projects
      </Button>
    </Stack>
  );
}
