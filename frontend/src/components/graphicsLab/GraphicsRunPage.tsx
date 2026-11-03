import { useState } from "react";
import { Alert, Badge, Button, Group, Loader, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useGraphicsRun,
  type GraphicEngine,
  type GraphicEngineKey,
  type GraphicRender,
} from "../../api/graphicsLab";
import { DeleteLabSampleButton } from "../lab/DeleteLabSampleButton";
import { GraphicsBriefPanel } from "./GraphicsBriefPanel";
import { GraphicsEngineCard } from "./GraphicsEngineCard";
import { GraphicsPlaybackBar } from "./GraphicsPlaybackBar";
import { GraphicsVoicePanel } from "./GraphicsVoicePanel";
import { ORIENTATION_LABELS } from "./graphicsLabView";
import { useSyncedVideos } from "./useSyncedVideos";

type GraphicsRunPageProps = {
  runId: number;
  onBack: () => void;
  /** Opens another run (Ask again makes one). */
  onOpenRun: (id: number) => void;
};

/**
 * One run, as the comparison of §4.9 (GFX-011): its line and its brief (GFX-003), one playback
 * bar that plays, pauses, steps and seeks every video together, and the four engine cards. A
 * landscape run shows the cards two by two, a portrait run in four columns.
 */
export function GraphicsRunPage({ runId, onBack, onOpenRun }: GraphicsRunPageProps) {
  const run = useGraphicsRun(runId);
  const data = run.data;

  // The attempt each card shows. An engine not in the map shows its newest.
  const [chosen, setChosen] = useState<Partial<Record<GraphicEngineKey, number>>>({});
  const [showSafeArea, setShowSafeArea] = useState(false);
  const [showCaptionArea, setShowCaptionArea] = useState(false);

  const shownOf = (engine: GraphicEngine): GraphicRender | undefined =>
    engine.renders.find((render) => render.id === chosen[engine.key]) ?? engine.renders[0];
  const engines = data?.engines ?? [];
  const withVideo = engines.filter((engine) => shownOf(engine)?.url != null);
  const frames = data?.resolved?.frames ?? 1;

  const sync = useSyncedVideos({
    fps: data?.fps ?? 24,
    frames,
    keys: withVideo.map((engine) => engine.key),
  });

  function choose(key: GraphicEngineKey, renderId: number | null) {
    setChosen((current) => {
      const next = { ...current };
      if (renderId === null) {
        delete next[key];
      } else {
        next[key] = renderId;
      }
      return next;
    });
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Button variant="subtle" size="compact-sm" onClick={onBack}>
          ← All runs
        </Button>
        {data && <DeleteLabSampleButton kind="graphic_run" sampleId={data.id} onDeleted={onBack} />}
      </Group>

      {run.isLoading && <Loader size="sm" />}
      {run.isError && (
        <Alert color="red" title="Could not load the run">
          {describeError(run.error)}
        </Alert>
      )}

      {data && (
        <>
          <Group gap="xs">
            <Title order={4}>Run {data.id}</Title>
            <Badge variant="outline">{ORIENTATION_LABELS[data.orientation]}</Badge>
            <Text size="xs" c="dimmed">
              {data.width} x {data.height}, {data.fps} frames a second
            </Text>
          </Group>

          <Paper withBorder p="md" radius="md">
            <Stack gap={4}>
              <Text size="xs" fw={600} c="dimmed">
                The line
              </Text>
              <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {data.line_text}
              </Text>
            </Stack>
          </Paper>

          {data.voice !== null && <GraphicsVoicePanel voice={data.voice} />}

          <GraphicsBriefPanel run={data} onOpenRun={onOpenRun} />

          <GraphicsPlaybackBar
            sync={sync}
            resolved={data.resolved}
            frames={frames}
            fps={data.fps}
            hasVideos={withVideo.length > 0}
            showSafeArea={showSafeArea}
            onShowSafeArea={setShowSafeArea}
            showCaptionArea={showCaptionArea}
            onShowCaptionArea={setShowCaptionArea}
          />

          <SimpleGrid cols={data.orientation === "portrait" ? { base: 2, md: 4 } : { base: 1, sm: 2 }}>
            {data.engines.map((engine) => (
              <GraphicsEngineCard
                key={engine.key}
                runId={data.id}
                engine={engine}
                shown={shownOf(engine)}
                width={data.width}
                height={data.height}
                resolved={data.resolved}
                showSafeArea={showSafeArea}
                showCaptionArea={showCaptionArea}
                videoRef={sync.register(engine.key)}
                onLoaded={() => sync.onLoaded(engine.key)}
                onShow={(renderId) => choose(engine.key, renderId)}
              />
            ))}
          </SimpleGrid>
        </>
      )}
    </Stack>
  );
}
