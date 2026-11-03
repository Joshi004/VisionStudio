import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  List,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { useRunGraphicBrief } from "../../api/graphicBriefs";
import {
  useAskGraphicAgain,
  useMakeShotGraphics,
  useShotGraphics,
  type ShotGraphic,
  type ShotGraphicAttempt,
  type ShotGraphicEngine,
  type ShotGraphicScene,
} from "../../api/shotGraphics";
import { GraphicsBlockScene } from "../graphicsLab/GraphicsBlockScene";
import { GraphicsComponentCode } from "../graphicsLab/GraphicsComponentCode";
import { GraphicsPlaybackBar } from "../graphicsLab/GraphicsPlaybackBar";
import { GraphicsRenderMetrics } from "../graphicsLab/GraphicsRenderMetrics";
import { GraphicsVideoFrame } from "../graphicsLab/GraphicsVideoFrame";
import { useSyncedVideos, type SyncedVideos } from "../graphicsLab/useSyncedVideos";

type GraphicsPanelProps = {
  projectId: number;
};

const SHOT_BADGE: Record<ShotGraphic["status"], { label: string; color: string }> = {
  none: { label: "Nothing made yet", color: "gray" },
  working: { label: "Being made", color: "blue" },
  ready: { label: "Ready", color: "green" },
  failed: { label: "Failed", color: "red" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

const ENGINE_BADGE: Record<ShotGraphicEngine["status"], { label: string; color: string }> = {
  none: { label: "Nothing yet", color: "gray" },
  writing: { label: "Writing", color: "blue" },
  rendering: { label: "Drawing", color: "blue" },
  ready: { label: "Ready", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
  failed: { label: "Failed", color: "red" },
};

// Used when the shot cannot be worked out now (no player is shown then).
const FALLBACK_FPS = 30;

/**
 * The graphics stage of a continuous explainer: for each graphic shot, both versions side by
 * side (the generated component and the building blocks), each drawn to an exact silent clip
 * from the shot's brief, the project's theme and the voice take. One playback bar plays both
 * together with the voice take, so the versions are judged against what is said.
 */
export function GraphicsPanel({ projectId }: GraphicsPanelProps) {
  const { data, isLoading, isError, error } = useShotGraphics(projectId);
  const make = useMakeShotGraphics(projectId);
  const askAgain = useAskGraphicAgain(projectId);
  const writeBrief = useRunGraphicBrief(projectId);

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="xs">
          <Title order={4}>Graphics</Title>
          <Text size="sm" c="dimmed">
            Each graphic shot is made in two versions: a component the model writes as code, and a
            scene the model builds from ready-made blocks. Both are drawn from the shot's brief
            and the project's theme, with the words on the beats they were spoken at. The clips
            have no sound; the voice take plays with them.
          </Text>
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the graphics">
              {describeError(error)}
            </Alert>
          )}
          {make.isError && (
            <Alert color="red" title="Could not make the graphics">
              {describeError(make.error)}
            </Alert>
          )}
          {askAgain.isError && (
            <Alert color="red" title="Could not ask again">
              {describeError(askAgain.error)}
            </Alert>
          )}
          {writeBrief.isError && (
            <Alert color="red" title="Could not start the graphic brief">
              {describeError(writeBrief.error)}
            </Alert>
          )}
          {data?.blocked_reason && (
            <Text size="sm" c="dimmed">
              {data.blocked_reason}
            </Text>
          )}
          {data?.wanted && data.scenes.length === 0 && (
            <Text size="sm" c="dimmed">
              No scene has a graphic shot yet. Graphic shots appear when the shots of a scene are
              planned.
            </Text>
          )}
        </Stack>
      </Paper>

      {data?.scenes.map((scene) => (
        <SceneGraphics
          key={scene.id}
          scene={scene}
          busy={make.isPending || askAgain.isPending || writeBrief.isPending}
          onMake={(shot) => make.mutate({ sceneId: scene.id, shotId: shot.id })}
          onAskAgain={(shot, engine) =>
            askAgain.mutate({ sceneId: scene.id, shotId: shot.id, engine })
          }
          onWriteBrief={(shot) => writeBrief.mutate({ sceneId: scene.id, shotId: shot.id })}
        />
      ))}
    </Stack>
  );
}

type SceneGraphicsProps = {
  scene: ShotGraphicScene;
  busy: boolean;
  onMake: (shot: ShotGraphic) => void;
  onAskAgain: (shot: ShotGraphic, engine: ShotGraphicEngine["key"]) => void;
  onWriteBrief: (shot: ShotGraphic) => void;
};

function SceneGraphics({ scene, busy, onMake, onAskAgain, onWriteBrief }: SceneGraphicsProps) {
  return (
    <Stack gap="xs">
      <Text fw={600}>{scene.index !== null ? `Scene ${scene.index}: ${scene.title}` : scene.title}</Text>
      {scene.shots.map((shot) => (
        <ShotGraphics
          key={shot.id}
          shot={shot}
          busy={busy}
          onMake={onMake}
          onAskAgain={onAskAgain}
          onWriteBrief={onWriteBrief}
        />
      ))}
    </Stack>
  );
}

/** The attempt a version shows: the one chosen, else the newest that has a video, else the newest. */
function shownAttempt(
  engine: ShotGraphicEngine,
  chosenId: number | undefined,
): ShotGraphicAttempt | undefined {
  return (
    engine.attempts.find((attempt) => attempt.id === chosenId) ??
    engine.attempts.find((attempt) => attempt.url !== null) ??
    engine.attempts[0]
  );
}

type ShotGraphicsProps = {
  shot: ShotGraphic;
  busy: boolean;
  onMake: (shot: ShotGraphic) => void;
  onAskAgain: (shot: ShotGraphic, engine: ShotGraphicEngine["key"]) => void;
  onWriteBrief: (shot: ShotGraphic) => void;
};

function ShotGraphics({ shot, busy, onMake, onAskAgain, onWriteBrief }: ShotGraphicsProps) {
  const [chosen, setChosen] = useState<Partial<Record<ShotGraphicEngine["key"], number>>>({});
  const [showSafeArea, setShowSafeArea] = useState(false);
  const [showCaptionArea, setShowCaptionArea] = useState(false);

  const { resolved } = shot;
  const fps = resolved?.fps ?? FALLBACK_FPS;
  const frames = resolved?.frames ?? 1;
  const working = shot.status === "working";
  const badge = SHOT_BADGE[shot.status];

  const shown = shot.engines.map((engine) => ({
    engine,
    attempt: shownAttempt(engine, chosen[engine.key]),
  }));
  // Only the versions that have a video are played; the first is the leader of the player.
  const withVideo = shown.filter(({ attempt }) => attempt?.url != null);
  const sync = useSyncedVideos({
    fps,
    frames,
    keys: withVideo.map(({ engine }) => engine.key),
    audioOffsetS: shot.voice?.offset_s ?? null,
  });

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={4}>
            <Group gap="xs">
              <Text size="sm" fw={600}>
                {shot.id.replace("shot_", "Shot ")}
              </Text>
              <Badge color={badge.color} variant="light">
                {badge.label}
              </Badge>
              {working && <Loader size="xs" />}
              <Text size="xs" c="dimmed">
                {shot.start_s.toFixed(1)} to {shot.end_s.toFixed(1)} s
              </Text>
              {shot.brief_version !== null && (
                <Text size="xs" c="dimmed">
                  Brief version {shot.brief_version}
                </Text>
              )}
            </Group>
            <Text size="sm" fw={600} style={{ wordBreak: "break-word" }}>
              {shot.spoken_text}
            </Text>
            <Text size="xs" c="dimmed">
              Planner's description: {shot.description}
            </Text>
          </Stack>
          <Group gap="xs">
            <Button
              size="compact-sm"
              variant="default"
              disabled={busy || shot.brief_status === "writing"}
              onClick={() => onWriteBrief(shot)}
              title="Writes the brief of this shot again (one model call). The graphics are not made again until you press Make the graphics."
            >
              Write the brief again
            </Button>
            <Button
              size="compact-sm"
              loading={working || busy}
              disabled={!shot.can_run}
              onClick={() => onMake(shot)}
            >
              Make the graphics
            </Button>
          </Group>
        </Group>

        {!shot.can_run && !working && shot.blocked_reason !== null && (
          <Text size="xs" c="dimmed">
            {shot.blocked_reason}
          </Text>
        )}
        {shot.last_error && (
          <Text size="sm" c="red" style={{ wordBreak: "break-word" }}>
            {shot.last_error}
          </Text>
        )}
        {shot.status === "out_of_date" && (
          <Alert color="yellow" title="Out of date">
            <Stack gap={4}>
              <Text size="sm">
                Something these graphics were made from has changed. Press Make the graphics to
                draw them again.
              </Text>
              {shot.reasons.length > 0 && (
                <List size="sm">
                  {shot.reasons.map((reason) => (
                    <List.Item key={reason}>{reason}</List.Item>
                  ))}
                </List>
              )}
            </Stack>
          </Alert>
        )}

        {resolved !== null && (
          <GraphicsPlaybackBar
            sync={sync}
            resolved={resolved}
            frames={frames}
            fps={fps}
            hasVideos={withVideo.length > 0}
            showSafeArea={showSafeArea}
            onShowSafeArea={setShowSafeArea}
            showCaptionArea={showCaptionArea}
            onShowCaptionArea={setShowCaptionArea}
          />
        )}
        {shot.voice !== null && <VoiceAudio url={shot.voice.url} register={sync.registerAudio} />}

        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
          {shown.map(({ engine, attempt }) => (
            <VersionCard
              key={engine.key}
              engine={engine}
              attempt={attempt}
              shot={shot}
              onShow={(attemptId) => setChosen((now) => ({ ...now, [engine.key]: attemptId }))}
              showSafeArea={showSafeArea}
              showCaptionArea={showCaptionArea}
              sync={sync}
              askingDisabled={
                busy ||
                !shot.can_run ||
                engine.status === "writing" ||
                engine.status === "rendering"
              }
              onAskAgain={() => onAskAgain(shot, engine.key)}
            />
          ))}
        </SimpleGrid>
      </Stack>
    </Paper>
  );
}

/** The scene's voice take, which the playback bar plays with the silent clips. It has no controls. */
function VoiceAudio({
  url,
  register,
}: {
  url: string;
  register: (element: HTMLAudioElement | null) => void;
}) {
  return <audio ref={register} src={url} preload="auto" />;
}

type VersionCardProps = {
  engine: ShotGraphicEngine;
  attempt: ShotGraphicAttempt | undefined;
  shot: ShotGraphic;
  onShow: (attemptId: number) => void;
  showSafeArea: boolean;
  showCaptionArea: boolean;
  /** The shared player; the card joins it with its video. */
  sync: SyncedVideos;
  askingDisabled: boolean;
  onAskAgain: () => void;
};

function VersionCard({
  engine,
  attempt,
  shot,
  onShow,
  showSafeArea,
  showCaptionArea,
  sync,
  askingDisabled,
  onAskAgain,
}: VersionCardProps) {
  const badge = ENGINE_BADGE[engine.status];
  const busy = engine.status === "writing" || engine.status === "rendering";
  const { resolved } = shot;
  // The attempt a repair was made from (a component whose render failed), when it is shown.
  const repairedAttempt =
    attempt?.repair_of != null
      ? engine.attempts.find((item) => item.id === attempt.repair_of)
      : undefined;

  return (
    <Paper withBorder p="sm" radius="md" data-engine={engine.key}>
      <Stack gap="xs">
        <Group justify="space-between" gap="xs">
          <Text size="sm" fw={600}>
            {engine.label}
          </Text>
          <Group gap={6} wrap="nowrap">
            {busy && <Loader size="xs" />}
            <Badge color={badge.color} variant="light">
              {badge.label}
            </Badge>
          </Group>
        </Group>

        {engine.failed_outright && (
          <Alert color="red" p="xs" title="The generated component failed">
            Its repairs are used up and nothing more will be tried for it. Ask again to try a new
            one.
          </Alert>
        )}

        {resolved !== null ? (
          <GraphicsVideoFrame
            url={attempt?.url ?? null}
            width={resolved.width}
            height={resolved.height}
            resolved={resolved}
            showSafeArea={showSafeArea}
            showCaptionArea={showCaptionArea}
            emptyText={busy ? "Being made" : "No video yet"}
            videoRef={sync.register(engine.key)}
            onLoaded={() => sync.onLoaded(engine.key)}
          />
        ) : (
          <Text size="xs" c="dimmed">
            The video cannot be shown until the theme, the brief and the voice take are ready.
          </Text>
        )}

        {attempt !== undefined && (
          <>
            <Text size="xs" c="dimmed">
              Attempt {attempt.attempt}
              {engine.attempts.length > 1 ? ` of ${engine.attempts.length}` : ""}
              {attempt.url !== null && !attempt.current ? ", drawn for an earlier look" : ""}
              {repairedAttempt !== undefined ? `, a repair of attempt ${repairedAttempt.attempt}` : ""}
            </Text>
            {engine.key === "remotion_blocks" && <GraphicsBlockScene render={attempt} />}
            {engine.key === "generated_component" && <GraphicsComponentCode render={attempt} />}
            <GraphicsRenderMetrics
              render={{
                metrics: attempt.metrics,
                warnings: attempt.warnings,
                input_call: attempt.input_call,
                repeat_of: attempt.rerender_of,
              }}
            />
            {attempt.last_error !== null && (
              <Text size="xs" c="red" style={{ wordBreak: "break-word" }}>
                {attempt.last_error}
              </Text>
            )}
          </>
        )}
        {attempt === undefined && engine.last_error !== null && (
          <Text size="xs" c="red" style={{ wordBreak: "break-word" }}>
            {engine.last_error}
          </Text>
        )}

        <Button
          size="compact-xs"
          variant="default"
          onClick={onAskAgain}
          disabled={askingDisabled}
          title="A paid model call: makes this version again as a new attempt, from the same brief."
          style={{ alignSelf: "flex-start" }}
        >
          Ask again
        </Button>

        {engine.attempts.length > 1 && (
          <Group gap={4}>
            {engine.attempts.map((item) => (
              <Button
                key={item.id}
                size="compact-xs"
                variant={item.id === attempt?.id ? "filled" : "default"}
                color={item.url === null ? "gray" : undefined}
                onClick={() => onShow(item.id)}
              >
                {item.attempt}
              </Button>
            ))}
          </Group>
        )}
      </Stack>
    </Paper>
  );
}
