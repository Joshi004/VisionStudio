import { useState } from "react";
import { Alert, Badge, Button, Group, Loader, Paper, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import type { ProjectDetail } from "../../api/projects";
import { useRenders, useStartRender } from "../../api/renders";
import { useScenes } from "../../api/scenes";
import { useNow } from "../../hooks/useNow";
import { useRefreshWhenFinished } from "../../hooks/useRefreshWhenFinished";
import { JobActions } from "../jobs/JobActions";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { downloadName, renderLine, renderSummary } from "./renderView";

/**
 * The final video: Render, the status of the newest render, a player for a finished render
 * (the newest, or one picked from the list) and a Download button for each.
 */
export function RenderSection({ project }: { project: ProjectDetail }) {
  // Both queries are shared with the other sections: one request and one cache entry each.
  const scenesQuery = useScenes(project.id);
  const rendersQuery = useRenders(project.id);
  const start = useStartRender(project.id);
  // The render picked from the list, and the newest render at that moment: a render that
  // finishes later is shown instead, without any effect or timer.
  const [choice, setChoice] = useState<{ assetId: number; newestAssetId: number } | null>(null);

  const scenes = scenesQuery.data?.scenes ?? [];
  const blockedReason = scenesQuery.data?.render_blocked_reason ?? null;
  const job = rendersQuery.data?.job ?? null;
  const renders = rendersQuery.data?.renders ?? [];

  const isActive = isJobActive(job);
  // Elapsed times are worked out from the stored times and the clock, which ticks once a
  // second while the render is waiting or running. When it finishes, the whole page is loaded.
  const now = useNow(isActive, rendersQuery.dataUpdatedAt);
  useRefreshWhenFinished(isActive);
  const newest = renders[0] ?? null;
  const picked =
    choice !== null && choice.newestAssetId === newest?.asset_id
      ? renders.find((render) => render.asset_id === choice.assetId)
      : undefined;
  const shown = picked ?? newest;

  const disabledReason = isActive ? "A render is already in progress." : blockedReason;
  const isLoading = scenesQuery.isLoading || rendersQuery.isLoading;
  const loadError = rendersQuery.isError ? rendersQuery.error : null;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="center" wrap="nowrap">
          <Title order={4}>Final video</Title>
          <Button
            onClick={() => start.mutate()}
            loading={start.isPending}
            disabled={isLoading || disabledReason !== null}
          >
            {renders.length > 0 ? "Render again" : "Render"}
          </Button>
        </Group>

        {disabledReason !== null ? (
          <Text size="sm" c="dimmed">
            {disabledReason}
          </Text>
        ) : (
          <Text size="sm" c="dimmed">
            {renderSummary(scenes, project.clip_sound_volume)} It takes about a minute or two. Each
            render is kept, so you can compare them.
          </Text>
        )}

        {isLoading && <Loader size="sm" />}

        {loadError && (
          <Alert color="red" title="Could not load the renders">
            {describeError(loadError)} Press Refresh to try again.
          </Alert>
        )}

        {start.isError && (
          <Alert color="red" title="The render was not started">
            {describeError(start.error)}
          </Alert>
        )}

        {job !== null && (
          <Stack gap={4}>
            <Group gap="sm">
              <JobStatusBadge job={job} />
              <Text size="sm" c="dimmed">
                {elapsedText(job, now)}
              </Text>
              <JobActions job={job} />
            </Group>
            {isActive && (
              <Text size="xs" c="dimmed">
                This updates by itself.
              </Text>
            )}
          </Stack>
        )}

        {job?.status === "failed" && job.error && (
          <Alert color="red" title="The render failed">
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {job.error}
            </Text>
          </Alert>
        )}

        {rendersQuery.data && shown === null && !isActive && (
          <Text size="sm" c="dimmed">
            No render yet.
          </Text>
        )}

        {shown !== null && (
          <Stack gap="xs">
            {/* Keyed by the file, so another render always loads fresh. */}
            <video
              key={shown.asset_id}
              src={shown.url}
              controls
              preload="metadata"
              playsInline
              style={{
                display: "block",
                maxWidth: "100%",
                maxHeight: 520,
                margin: "0 auto",
                background: "#000",
              }}
            />
            <Group justify="space-between" gap="sm">
              <Text size="xs" c="dimmed" style={{ flex: 1 }}>
                {renderLine(shown)}
              </Text>
              <Button
                component="a"
                href={shown.url}
                download={downloadName(project.name, shown.job_id)}
                variant="default"
                size="compact-sm"
              >
                Download
              </Button>
            </Group>
          </Stack>
        )}

        {renders.length > 1 && (
          <Stack gap={6}>
            <Text size="sm" fw={600}>
              All renders
            </Text>
            {renders.map((render, index) => (
              <Group key={render.asset_id} justify="space-between" gap="sm" wrap="nowrap">
                <Group gap="xs" style={{ flex: 1 }} wrap="nowrap">
                  {render.asset_id === shown?.asset_id ? (
                    <Badge variant="light">Showing</Badge>
                  ) : (
                    <Button
                      size="compact-xs"
                      variant="default"
                      onClick={() =>
                        setChoice({
                          assetId: render.asset_id,
                          newestAssetId: renders[0].asset_id,
                        })
                      }
                    >
                      Play
                    </Button>
                  )}
                  <Text size="xs" c="dimmed">
                    {index === 0 ? "Newest · " : ""}
                    {renderLine(render)}
                  </Text>
                </Group>
                <Button
                  component="a"
                  href={render.url}
                  download={downloadName(project.name, render.job_id)}
                  size="compact-xs"
                  variant="subtle"
                >
                  Download
                </Button>
              </Group>
            ))}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
