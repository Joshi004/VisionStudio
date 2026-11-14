import { Group, Text, Tooltip } from "@mantine/core";

import { useHealth } from "../api/health";

/**
 * A small warning mark for when the status next to it is not fresh: the last poll could not
 * reach the backend, so this is simply the last status it gave before that. Hovering explains
 * why.
 */
function StaleMark() {
  return (
    <Tooltip label="The server is not responding. Showing its last known status." withArrow>
      <Text
        component="span"
        size="sm"
        c="orange"
        fw={700}
        aria-label="The server is not responding"
        style={{ cursor: "help" }}
      >
        ⚠
      </Text>
    </Tooltip>
  );
}

export function BackendStatus() {
  const { data, isLoading, isRefetchError } = useHealth();

  if (isLoading) {
    return (
      <Text size="sm" c="dimmed">
        Checking backend…
      </Text>
    );
  }

  // No answer has ever come back: there is no earlier status to fall back to.
  if (!data) {
    return (
      <Text size="sm" c="red">
        Backend unreachable
      </Text>
    );
  }

  // A later poll failed, but `data` still holds the last one that succeeded (React Query
  // keeps it rather than clearing it): show that status, marked as possibly stale.
  const stale = isRefetchError ? <StaleMark /> : null;

  if (data.status === "degraded") {
    const failedParts: string[] = [];
    if (!data.database.ok) {
      failedParts.push("database");
    }
    if (!data.files.ok) {
      failedParts.push("files folder");
    }
    if (!data.ffmpeg.ok) {
      failedParts.push("FFmpeg");
    }
    if (!data.ffprobe.ok) {
      failedParts.push("ffprobe");
    }

    return (
      <Group gap={6} wrap="nowrap">
        {stale}
        <Text size="sm" c="orange">
          Backend degraded: {failedParts.join(", ")}
        </Text>
      </Group>
    );
  }

  return (
    <Group gap={6} wrap="nowrap">
      {stale}
      <Text size="sm" c="green">
        Backend OK · FFmpeg {data.ffmpeg.version ?? "unknown"}
      </Text>
    </Group>
  );
}
