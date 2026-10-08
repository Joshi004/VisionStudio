import { useState } from "react";
import { Alert, Anchor, Badge, Button, Group, Modal, SimpleGrid, Stack, Text } from "@mantine/core";
import { Link } from "react-router";

import { describeError } from "../../api/errors";
import { useGenerateFirstFrame, useSelectFirstFrame } from "../../api/firstFrames";
import type { ProjectDetail } from "../../api/projects";
import type { Frame } from "../../api/sceneInputs";
import type { Scene } from "../../api/scenes";
import { formatDateTime } from "../../format";
import { JobActions } from "../jobs/JobActions";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { hasActiveFrameJob, hasAiFrame } from "./firstFrameView";

/** Who made a frame, and whether it is out of date: "Uploaded" or "AI", and "Out of date". */
export function FirstFrameBadges({ frame }: { frame: Pick<Frame, "source" | "out_of_date"> }) {
  return (
    <>
      <Badge color={frame.source === "ai" ? "grape" : "gray"} variant="light">
        {frame.source === "ai" ? "AI" : "Uploaded"}
      </Badge>
      {frame.out_of_date && (
        <Badge color="orange" variant="light">
          Out of date
        </Badge>
      )}
    </>
  );
}

type FirstFrameActionsProps = {
  project: ProjectDetail;
  scene: Scene;
  /** The image model, for the confirmation. */
  model: string;
  /** Bitdeer's price for one image, in US dollars, for the confirmation. */
  pricePerImage: number;
  /**
   * The drawer holds changes that are not saved yet. The frame is made from the saved image
   * prompt, so they are saved first.
   */
  edited: boolean;
  /** The current time in milliseconds since 1970, for the elapsed time. */
  now: number;
};

/**
 * Generate first frame (or Regenerate) for one scene: one paid image from the image model, with a
 * confirmation, then the status of the newest job. Replacing a frame the user uploaded asks
 * first, and the upload stays in the list of earlier frames, which can be used again here.
 */
export function FirstFrameActions({
  project,
  scene,
  model,
  pricePerImage,
  edited,
  now,
}: FirstFrameActionsProps) {
  const generate = useGenerateFirstFrame(project.id);
  const select = useSelectFirstFrame(project.id);
  // Set while the confirmation of Generate is open. `replaceUpload` says the frame in the slot
  // is an upload that this click replaces.
  const [confirming, setConfirming] = useState<{ replaceUpload: boolean } | null>(null);
  // Set while the confirmation of "Use this" is open (the frame in use would no longer be listed).
  const [choosing, setChoosing] = useState<Frame | null>(null);

  const current = scene.first_frame;
  const job = scene.frame_job;
  const active = hasActiveFrameJob(scene);
  const isAi = hasAiFrame(scene);
  const isUpload = current !== null && !isAi;
  const choices = scene.first_frame_choices;
  const currentListed = current !== null && choices.some((frame) => frame.asset_id === current.asset_id);
  // The server's reason first (no current image prompt, or none at all), then the two the page
  // knows about itself.
  const blocked =
    scene.frame_blocked_reason ??
    (active ? "An image is already being made." : null) ??
    (edited ? "Save your changes first." : null);

  function start() {
    if (confirming === null) {
      return;
    }
    generate.mutate({ sceneId: scene.id, replaceUpload: confirming.replaceUpload });
    setConfirming(null);
  }

  function use(frame: Frame) {
    select.reset();
    if (current !== null && !currentListed) {
      setChoosing(frame);
      return;
    }
    select.mutate({ sceneId: scene.id, assetId: frame.asset_id });
  }

  function confirmUse() {
    if (choosing === null) {
      return;
    }
    select.mutate({ sceneId: scene.id, assetId: choosing.asset_id });
    setChoosing(null);
  }

  return (
    <Stack gap={8}>
      <Group gap="sm" align="center">
        <Button
          size="xs"
          variant="default"
          disabled={blocked !== null}
          loading={generate.isPending}
          onClick={() => {
            generate.reset();
            setConfirming({ replaceUpload: isUpload });
          }}
        >
          {isAi ? "Regenerate first frame" : "Generate first frame"}
        </Button>
        {blocked !== null && (
          <Text size="xs" c="dimmed" style={{ flex: 1 }}>
            {blocked}
          </Text>
        )}
      </Group>
      <Text size="xs" c="dimmed">
        Made by the image model from the image prompt above: one paid image, about ${pricePerImage},
        20 to 50 seconds. The bottom strip, where the model stamps its label, is cut off, and the
        frame is exactly {project.gen_width} x {project.gen_height}.
      </Text>

      {generate.isError && (
        <Alert color="red" title="The first frame was not started">
          {describeError(generate.error)}
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
          {active && (
            <Text size="xs" c="dimmed">
              An image takes 20 to 50 seconds. This updates by itself.
            </Text>
          )}
        </Stack>
      )}
      {job?.status === "failed" && job.error && (
        <Alert color="red" title="The first frame was not made">
          <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {job.error}
          </Text>
        </Alert>
      )}
      {scene.frame_job_note !== null && (
        <Text size="xs" c="orange.8">
          {scene.frame_job_note}
        </Text>
      )}
      {current !== null && current.job_id !== null && (
        <Text size="xs" c="dimmed">
          The image model made this frame in job {current.job_id}. Its exact request and answer
          are on the{" "}
          <Anchor component={Link} to="/activity" size="xs">
            Activity page
          </Anchor>
          .
        </Text>
      )}
      {scene.first_frame_out_of_date && (
        <Text size="xs" c="orange.8">
          The image prompt changed after this frame was made. Regenerate it, or keep it.
        </Text>
      )}

      <Text size="sm" fw={600}>
        Earlier frames
      </Text>
      {choices.length === 0 ? (
        <Text size="xs" c="dimmed">
          No earlier frames yet. Every frame the image model makes is kept here, and so is a frame
          you uploaded when one is made over it.
        </Text>
      ) : (
        <SimpleGrid cols={3} spacing="sm">
          {choices.map((frame) => {
            const inUse = current?.asset_id === frame.asset_id;
            return (
              <Stack key={frame.asset_id} gap={4}>
                <img
                  src={frame.preview_url}
                  alt={`${frame.source === "ai" ? "AI" : "Uploaded"} frame ${frame.asset_id}`}
                  loading="lazy"
                  style={{
                    width: "100%",
                    aspectRatio: `${project.gen_width} / ${project.gen_height}`,
                    objectFit: "contain",
                    borderRadius: "var(--mantine-radius-sm)",
                    border: "1px solid var(--mantine-color-gray-4)",
                    background: "var(--mantine-color-gray-light)",
                  }}
                />
                <Group gap={4}>
                  <FirstFrameBadges frame={frame} />
                  {inUse && (
                    <Badge color="green" variant="light">
                      In use
                    </Badge>
                  )}
                </Group>
                <Text size="xs" c="dimmed">
                  {formatDateTime(frame.created_at)}
                </Text>
                <Button
                  size="compact-xs"
                  variant="default"
                  disabled={inUse || select.isPending || active}
                  onClick={() => use(frame)}
                >
                  Use this
                </Button>
              </Stack>
            );
          })}
        </SimpleGrid>
      )}
      {select.isError && (
        <Alert color="red" title="That frame was not used">
          {describeError(select.error)}
        </Alert>
      )}

      <Modal
        opened={confirming !== null}
        onClose={() => setConfirming(null)}
        title="Before the image model is called"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            One paid image with {model}, about ${pricePerImage}, 20 to 50 s. It is made from the
            saved image prompt of scene {scene.index + 1}, and nothing is reused: a failed call is
            not retried.
          </Text>
          {confirming?.replaceUpload ? (
            <Text size="sm">
              Your uploaded frame is replaced. It stays in the list of earlier frames, and you can
              use it again.
            </Text>
          ) : (
            current !== null && (
              <Text size="sm">The current frame stays in the list of earlier frames.</Text>
            )
          )}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
            <Button onClick={start}>Continue</Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={choosing !== null}
        onClose={() => setChoosing(null)}
        title="Use this frame?"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            The frame in use now is not in this list, so it will no longer be offered here. Its
            file stays on disk.
          </Text>
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setChoosing(null)}>
              Cancel
            </Button>
            <Button onClick={confirmUse}>Use this frame</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
