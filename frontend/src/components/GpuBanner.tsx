import type { ReactNode } from "react";
import { Alert, Anchor, Stack } from "@mantine/core";
import { Link } from "react-router";

import { useGpuStatus, type GpuStatus } from "../api/gpu";
import { formatDateTime } from "../format";

/** The red banner: the server does not answer, or its API could not be fetched. */
function serverBanner(status: GpuStatus): ReactNode {
  const { server, contract } = status;

  if (server.state === "unreachable") {
    return (
      <Alert color="red" title="GPU server unreachable">
        Last checked {server.checked_at ? formatDateTime(server.checked_at) : "recently"} at{" "}
        {server.called_url}: {server.error ?? "no answer"}. Jobs that need it wait until it
        answers.
      </Alert>
    );
  }

  if (contract.state === "unreachable") {
    return (
      <Alert color="red" title="The GPU API could not be checked">
        {contract.message ?? "The server did not answer."}
        {contract.checked_at ? ` (checked ${formatDateTime(contract.checked_at)})` : ""}
      </Alert>
    );
  }

  return null;
}

/** The yellow or blue banner: the API changed, or has never been approved. */
function contractBanner(status: GpuStatus): ReactNode {
  const { contract, waiting_jobs: waitingJobs } = status;

  if (contract.state === "changed") {
    const names = contract.sources
      .filter((item) => item.status === "changed" || item.status === "unreadable")
      .map((item) => item.name);
    return (
      <Alert color="yellow" title="GPU API changed">
        {names.length > 0 ? names.join(", ") : "The recorded API"} differs from the approved
        version
        {contract.checked_at ? ` (found ${formatDateTime(contract.checked_at)})` : ""}. New GPU
        jobs wait until you review and approve the change. Jobs waiting: {waitingJobs}.{" "}
        <Anchor component={Link} to="/settings" size="sm">
          Review in Settings
        </Anchor>
      </Alert>
    );
  }

  if (contract.state === "not_approved") {
    return (
      <Alert color="blue" title="GPU API not approved yet">
        The GPU API has not been approved yet. GPU jobs cannot start until you approve it in{" "}
        <Anchor component={Link} to="/settings" size="sm">
          Settings
        </Anchor>
        .
      </Alert>
    );
  }

  return null;
}

/**
 * Warnings about the GPU server and its API, on every page. It reads stored
 * state only, so it never waits for the GPU server. It shows nothing while the
 * status loads or if it cannot be loaded: the backend status in the header
 * already covers a backend that is down.
 */
export function GpuBanner() {
  const { data } = useGpuStatus();
  if (!data) {
    return null;
  }

  const server = serverBanner(data);
  const contract = contractBanner(data);
  if (!server && !contract) {
    return null;
  }

  return (
    <Stack gap="xs" mb="md">
      {server}
      {contract}
    </Stack>
  );
}
