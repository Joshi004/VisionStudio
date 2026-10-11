import { useState } from "react";
import { Alert, Anchor, Badge, Button, Group, Modal, SimpleGrid, Stack, Text } from "@mantine/core";
import { Link } from "react-router";

import { describeError } from "../../api/errors";
import { useGenerateFirstFrame, useSelectFirstFrame } from "../../api/firstFrames";
import { useGenerateLastFrame, useSelectLastFrame } from "../../api/lastFrames";
import type { ProjectDetail } from "../../api/projects";
import type { Frame, FrameSlotName } from "../../api/sceneInputs";
import type { Scene } from "../../api/scenes";
import { formatDateTime } from "../../format";
import { JobActions } from "../jobs/JobActions";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";

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
  /** Which frame of the scene: the first (made from the image prompt) or the last (made by editing the first). */
  slot?: FrameSlotName;
  /** The image model and its mode, for the confirmation ("Qwen-Image-2.1, quality"). */
  model: string;
  /**
   * The drawer holds changes that are not saved yet. The frame is made from the saved prompt, so
   * they are saved first.
   */
  edited: boolean;
  /** The current time in milliseconds since 1970, for the elapsed time. */
  now: number;
};

/**
 * Generate (or Regenerate) the first or the last frame of one scene: one image from the image
 * model, made on the GPU server, with a confirmation, then the status of the newest job. The
 * first frame is made from the image prompt, the last frame by editing the first frame with the
 * last frame prompt. Replacing a frame the user uploaded asks first, and the upload stays in the
 * list of earlier frames, which can be used again here.
 */
export function FirstFrameActions({
  project,
  scene,
  slot = "first",
  model,
  edited,
  now,
}: FirstFrameActionsProps) {
  const last = slot === "last";
  const generateFirst = useGenerateFirstFrame(project.id);
  const generateLast = useGenerateLastFrame(project.id);
  const selectFirst = useSelectFirstFrame(project.id);
  const selectLast = useSelectLastFrame(project.id);
  const generate = last ? generateLast : generateFirst;
  const select = last ? selectLast : selectFirst;
  // Set while the confirmation of Generate is open. `replaceUpload` says the frame in the slot
  // is an upload that this click replaces.
  const [confirming, setConfirming] = useState<{ replaceUpload: boolean } | null>(null);
  // Set while the confirmation of "Use this" is open (the frame in use would no longer be listed).
  const [choosing, setChoosing] = useState<Frame | null>(null);

  const noun = last ? "last frame" : "first frame";
  const current = last ? scene.last_frame : scene.first_frame;
  const job = last ? scene.last_frame_job : scene.frame_job;
  const active = job !== null && (job.status === "queued" || job.status === "running");
  const isAi = current?.source === "ai";
  const isUpload = current !== null && !isAi;
  const choices = last ? scene.last_frame_choices : scene.first_frame_choices;
  const outOfDate = last ? scene.last_frame_out_of_date : scene.first_frame_out_of_date;
  const jobNote = last ? scene.last_frame_job_note : scene.frame_job_note;
  const currentListed = current !== null && choices.some((frame) => frame.asset_id === current.asset_id);
  // The server's reason first (no current prompt, or none at all), then the two the page knows
  // about itself.
  const blocked =
    (last ? scene.last_frame_blocked_reason : scene.frame_blocked_reason) ??
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
      <Text size="sm" fw={600}>
        {last ? "Last frame" : "First frame"}
      </Text>
      {!last && scene.first_frame_chained && (
        <Text size="xs" c="dimmed">
          This scene continues the action of scene {scene.index}, so it starts on that scene's last
          frame. The app puts it here once it is made, and "Generate first frames" skips this
          scene. A frame made here is replaced when that last frame is made again.
        </Text>
      )}
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
          {isAi ? `Regenerate ${noun}` : `Generate ${noun}`}
        </Button>
        {blocked !== null && (
          <Text size="xs" c="dimmed" style={{ flex: 1 }}>
            {blocked}
          </Text>
        )}
      </Group>
      <Text size="xs" c="dimmed">
        {last
          ? `Made by ${model} on your GPU server, by editing the first frame with the last frame prompt above. `
          : `Made by ${model} on your GPU server from the image prompt above. `}
        It takes a few minutes. The picture is fitted to exactly {project.gen_width} x{" "}
        {project.gen_height}, which trims a little from its edges.
      </Text>

      {generate.isError && (
        <Alert color="red" title={`The ${noun} was not started`}>
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
              An image takes a few minutes. This updates by itself.
            </Text>
          )}
        </Stack>
      )}
      {job?.status === "failed" && job.error && (
        <Alert color="red" title={`The ${noun} was not made`}>
          <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {job.error}
          </Text>
        </Alert>
      )}
      {jobNote !== null && (
        <Text size="xs" c="orange.8">
          {jobNote}
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
      {outOfDate && (
        <Text size="xs" c="orange.8">
          {last
            ? "The last frame prompt, or the first frame this was made from, changed after this frame was made. Regenerate it, or keep it."
            : "The image prompt changed after this frame was made. Regenerate it, or keep it."}
        </Text>
      )}

      <Text size="sm" fw={600}>
        {last ? "Earlier last frames" : "Earlier frames"}
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
        title="Before the image is made"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            One image with {model} on your GPU server, a few minutes.{" "}
            {last
              ? `It is made by editing the first frame of scene ${scene.index + 1} with the saved last frame prompt`
              : `It is made from the saved image prompt of scene ${scene.index + 1}`}
            , and nothing is reused: a job that fails is not tried again by itself.
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
          {last && (
            <Text size="sm">
              A scene that continues this scene's action then starts on the new frame.
            </Text>
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
