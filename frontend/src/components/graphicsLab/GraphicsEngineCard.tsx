import { Badge, Button, Group, Loader, Paper, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useAskEngineAgain,
  useRenderGraphicAgain,
  type GraphicEngine,
  type GraphicRender,
  type GraphicResolved,
} from "../../api/graphicsLab";
import { GraphicsAttemptList } from "./GraphicsAttemptList";
import { GraphicsBlockScene } from "./GraphicsBlockScene";
import { GraphicsComponentCode } from "./GraphicsComponentCode";
import { GraphicsRenderMetrics } from "./GraphicsRenderMetrics";
import { GraphicsRenderVerdict } from "./GraphicsRenderVerdict";
import { GraphicsTemplateSpec } from "./GraphicsTemplateSpec";
import { GraphicsVideoFrame } from "./GraphicsVideoFrame";
import { renderState } from "./graphicsLabView";

/** The engines that draw from a template spec (GFX-006). They share one model call. */
const TEMPLATE_ENGINES: ReadonlyArray<GraphicEngine["key"]> = [
  "remotion_templates",
  "python_templates",
];

type GraphicsEngineCardProps = {
  runId: number;
  engine: GraphicEngine;
  /** The attempt the card shows: the newest unless one of the older ones was chosen. */
  shown: GraphicRender | undefined;
  /** The size of every video of the run, so the empty frame has the video's shape. */
  width: number;
  height: number;
  resolved: GraphicResolved | null;
  showSafeArea: boolean;
  showCaptionArea: boolean;
  /** The ref callback and the loaded event of this card's video in the synced player. */
  videoRef: (element: HTMLVideoElement | null) => void;
  onLoaded: () => void;
  /** Chooses the attempt to show (null: the newest). */
  onShow: (renderId: number | null) => void;
};

/**
 * One engine of a run (GFX-011). From the top: where the attempt stands, its video
 * (played with the others by the playback bar of the run page, with the overlays), what the
 * engine drew from, what was measured, the verdict and the note, **Ask again** and **Render
 * again**, and the earlier attempts. An engine that is not built says so. A retired engine (the
 * templates, EXG-008) shows its older attempts only: no Ask again and no Render again.
 */
export function GraphicsEngineCard({
  runId,
  engine,
  shown,
  width,
  height,
  resolved,
  showSafeArea,
  showCaptionArea,
  videoRef,
  onLoaded,
  onShow,
}: GraphicsEngineCardProps) {
  const askAgain = useAskEngineAgain();
  const renderAgain = useRenderGraphicAgain();
  const state = shown !== undefined ? renderState(shown) : null;
  const isTemplate = TEMPLATE_ENGINES.includes(engine.key);
  // Any attempt of the engine still being written or drawn stops a new click (the server agrees).
  const working = engine.renders.some((render) => renderState(render).busy);

  function ask() {
    askAgain.mutate({ runId, engine: engine.key }, { onSuccess: () => onShow(null) });
  }

  function repeat() {
    if (shown !== undefined) {
      renderAgain.mutate(shown.id, { onSuccess: () => onShow(null) });
    }
  }

  return (
    <Paper withBorder p="sm" radius="md" data-engine={engine.key}>
      <Stack gap="xs">
        <Group justify="space-between" gap="xs">
          <Text size="sm" fw={600}>
            {engine.label}
          </Text>
          {!engine.built && (
            <Badge variant="light" color="gray">
              Not built yet
            </Badge>
          )}
          {engine.retired && (
            <Badge variant="light" color="gray">
              Retired
            </Badge>
          )}
          {engine.built && !engine.retired && !engine.renderer_built && (
            <Badge variant="light" color="gray">
              Renderer not built yet
            </Badge>
          )}
        </Group>

        {engine.retired && (
          <Text size="xs" c="dimmed">
            Templates are no longer made. Older attempts are shown.
          </Text>
        )}

        {state !== null && (
          <Group gap={6} wrap="nowrap">
            {state.busy && <Loader size="xs" />}
            <Badge variant="light" color={state.color} style={{ maxWidth: "100%" }}>
              {state.label}
            </Badge>
          </Group>
        )}

        <GraphicsVideoFrame
          url={shown?.url ?? null}
          width={width}
          height={height}
          resolved={resolved}
          showSafeArea={showSafeArea}
          showCaptionArea={showCaptionArea}
          emptyText={engine.built ? "No video yet" : "Not built yet"}
          videoRef={videoRef}
          onLoaded={onLoaded}
        />

        {shown !== undefined && (
          <>
            <Text size="xs" c="dimmed">
              Attempt {shown.attempt}
              {engine.renders.length > 1 ? ` of ${engine.renders.length}` : ""}
            </Text>
            {isTemplate && <GraphicsTemplateSpec render={shown} />}
            {engine.key === "remotion_blocks" && <GraphicsBlockScene render={shown} />}
            {engine.key === "generated_component" && <GraphicsComponentCode render={shown} />}
            <GraphicsRenderMetrics render={shown} />
            {shown.last_error !== null && (
              <Text size="xs" c="red" style={{ wordBreak: "break-word" }}>
                {shown.last_error}
              </Text>
            )}
            <GraphicsRenderVerdict key={shown.id} render={shown} />
          </>
        )}

        {engine.built && !engine.retired && (
          <Stack gap={4}>
            <Group gap="xs">
              <Button
                size="compact-xs"
                variant="default"
                onClick={ask}
                loading={askAgain.isPending}
                disabled={working || resolved === null}
                title="A paid model call: writes this engine's input again and renders it as a new attempt."
              >
                {isTemplate ? "Ask again (both template cards)" : "Ask again"}
              </Button>
              <Button
                size="compact-xs"
                variant="default"
                onClick={repeat}
                loading={renderAgain.isPending}
                disabled={
                  working || shown?.url == null || shown.input === null || !engine.renderer_built
                }
                title="Free: renders the same input again and compares the frames with this attempt."
              >
                Render again
              </Button>
            </Group>
            {askAgain.isError && (
              <Text size="xs" c="red">
                {describeError(askAgain.error)}
              </Text>
            )}
            {renderAgain.isError && (
              <Text size="xs" c="red">
                {describeError(renderAgain.error)}
              </Text>
            )}
          </Stack>
        )}

        {shown !== undefined && (
          <GraphicsAttemptList renders={engine.renders} shownId={shown.id} onShow={onShow} />
        )}
      </Stack>
    </Paper>
  );
}
