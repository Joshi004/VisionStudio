import { Text } from "@mantine/core";

import { useHealth } from "../api/health";

export function BackendStatus() {
  const { data, isLoading, isError } = useHealth();

  if (isLoading) {
    return (
      <Text size="sm" c="dimmed">
        Checking backend…
      </Text>
    );
  }

  if (isError || !data) {
    return (
      <Text size="sm" c="red">
        Backend unreachable
      </Text>
    );
  }

  if (data.status === "degraded") {
    const failedParts: string[] = [];
    if (!data.database.ok) {
      failedParts.push("database");
    }
    if (!data.ffmpeg.ok) {
      failedParts.push("FFmpeg");
    }
    if (!data.ffprobe.ok) {
      failedParts.push("ffprobe");
    }

    return (
      <Text size="sm" c="orange">
        Backend degraded: {failedParts.join(", ")}
      </Text>
    );
  }

  return (
    <Text size="sm" c="green">
      Backend OK · FFmpeg {data.ffmpeg.version ?? "unknown"}
    </Text>
  );
}
