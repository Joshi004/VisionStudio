import { Button, Stack, Text, Title } from "@mantine/core";
import { isRouteErrorResponse, useNavigate, useRouteError } from "react-router";

export function RouteError() {
  const error = useRouteError();
  const navigate = useNavigate();

  let message = "Something went wrong.";
  if (isRouteErrorResponse(error)) {
    message = `${error.status} ${error.statusText}`;
  } else if (error instanceof Error) {
    message = error.message;
  }

  return (
    <Stack align="center" gap="sm" py="xl">
      <Title order={2}>Unexpected error</Title>
      <Text c="dimmed">{message}</Text>
      <Button onClick={() => navigate("/projects")}>Go to Projects</Button>
    </Stack>
  );
}
