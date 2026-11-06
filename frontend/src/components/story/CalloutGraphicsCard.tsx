import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  List,
  Loader,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import {
  useAskCalloutGraphicAgain,
  useCalloutGraphics,
  useMakeCalloutGraphic,
  useMakeCalloutGraphics,
  useSetCalloutGraphicChoice,
  type CalloutGraphic,
  type CalloutGraphicEngine,
  type CalloutGraphicEngineKey,
} from "../../api/calloutGraphics";
import { describeError } from "../../api/errors";

type CalloutGraphicsCardProps = {
  projectId: number;
};

const ENGINE_BADGE: Record<
  CalloutGraphicEngine["status"],
  { label: string; color: string }
> = {
  none: { label: "Nothing yet", color: "gray" },
  writing: { label: "Writing", color: "blue" },
  rendering: { label: "Drawing", color: "blue" },
  ready: { label: "Ready", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
  failed: { label: "Failed", color: "red" },
};

const TYPE_LABELS: Record<string, string> = {
  emphasis: "Emphasis",
  number: "Number",
  question: "Question",
  comparison: "Comparison",
  list: "List",
  section_title: "Section title",
};

function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

const CALLOUT_BADGE: Record<
  CalloutGraphic["status"],
  { label: string; color: string }
> = {
  none: { label: "Nothing yet", color: "gray" },
  working: { label: "Being made", color: "blue" },
  ready: { label: "Ready", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
  failed: { label: "Failed", color: "red" },
};

const AUTOMATIC = "automatic";

/** Which version the video uses for a callout, and why, in the owner's words. */
function usedText(callout: CalloutGraphic): string {
  const used = callout.used;
  if (used === null) {
    return "Nothing is ready to use yet.";
  }
  if (used.engine === "box") {
    return "A text box: both versions failed.";
  }
  const label =
    callout.engines.find((item) => item.key === used.engine)?.label ??
    used.engine;
  switch (used.because) {
    case "chosen":
      return `${label} (your choice).`;
    case "component_failed":
      return `${label}: the generated component failed.`;
    default:
      return `${label} (automatic).`;
  }
}

/**
 * The two versions of every callout of a motion explainer: a component the model writes in the
 * callout look, and a scene of building blocks it composes in the same look, each with a preview
 * (the callout on a grey backdrop). The owner chooses per callout which one the video uses, or
 * leaves it on Automatic: the component, and the blocks only when the component failed. A
 * callout whose two versions both failed is drawn as a text box. Nothing is shown for a project
 * that does not draw its callouts as motion graphics.
 */
export function CalloutGraphicsCard({ projectId }: CalloutGraphicsCardProps) {
  const { data, isLoading, isError, error } = useCalloutGraphics(projectId);
  const makeAll = useMakeCalloutGraphics(projectId);

  if (data !== undefined && !data.wanted) {
    return null;
  }

  const blocked = data?.blocked_reason ?? null;
  const working =
    data?.callouts.some((callout) => callout.status === "working") ?? false;
  const cannotRun = isLoading || isError || blocked !== null;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Callout graphics</Title>
            <Text size="sm" c="dimmed">
              Each callout that is turned on gets two versions in the callout
              look: a generated component and a scene of building blocks, with a
              preview of each. Every callout costs two model calls. Choose which
              version the video uses, or leave it on Automatic.
            </Text>
          </Stack>
          <Button
            onClick={() => makeAll.mutate()}
            loading={makeAll.isPending || working}
            disabled={cannotRun}
          >
            Make callout graphics
          </Button>
        </Group>

        {blocked !== null && (
          <Text size="sm" c="dimmed">
            {blocked}
          </Text>
        )}
        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the callout graphics">
            {describeError(error)}
          </Alert>
        )}
        {makeAll.isError && (
          <Alert color="red" title="Could not make the callout graphics">
            {describeError(makeAll.error)}
          </Alert>
        )}

        {data?.callouts.map((callout) => (
          <CalloutRow
            key={callout.id}
            projectId={projectId}
            callout={callout}
          />
        ))}
      </Stack>
    </Paper>
  );
}

function warningsOf(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

/** A callout: one line while closed, the choice and both versions with their previews open. */
function CalloutRow({
  projectId,
  callout,
}: {
  projectId: number;
  callout: CalloutGraphic;
}) {
  const [open, setOpen] = useState(false);
  const make = useMakeCalloutGraphic(projectId);
  const setChoice = useSetCalloutGraphicChoice(projectId);
  const badge = CALLOUT_BADGE[callout.status];
  const enabled = callout.engines.length > 0;
  const working = callout.status === "working";
  const idle = callout.status === "none" || callout.status === "out_of_date";
  const mutationError = make.error ?? setChoice.error;

  return (
    <Paper withBorder p="sm" radius="md" data-callout={callout.id}>
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start" gap="xs">
          <Stack gap={2}>
            <Group gap="xs">
              <Badge variant="outline">
                {TYPE_LABELS[callout.type] ?? callout.type}
              </Badge>
              <Text size="xs" c="dimmed">
                {formatClock(callout.estimated_start_s)}
                {callout.length_s !== null
                  ? `, drawn for ${callout.length_s} s`
                  : ""}
              </Text>
            </Group>
            {callout.texts.map((text) => (
              <Text key={text} size="sm" fw={600}>
                {text}
              </Text>
            ))}
            {enabled && (
              <Text size="xs" c="dimmed">
                Used in the video: {usedText(callout)}
              </Text>
            )}
          </Stack>
          {!enabled ? (
            <Badge color="gray" variant="light">
              Off
            </Badge>
          ) : (
            <Group gap="xs" wrap="nowrap">
              {working && <Loader size="xs" />}
              <Badge color={badge.color} variant="light">
                {badge.label}
              </Badge>
              <Button
                size="compact-xs"
                variant="default"
                onClick={() => setOpen((value) => !value)}
              >
                {open ? "Hide" : "Show"}
              </Button>
            </Group>
          )}
        </Group>

        {enabled && open && (
          <>
            {callout.used?.engine === "box" && (
              <Alert
                color="orange"
                p="xs"
                title="This callout will be a text box"
              >
                Both versions failed, and nothing more will be tried for them.
                Ask again on either version to try a new one.
              </Alert>
            )}
            {callout.reasons.length > 0 && (
              <List size="xs">
                {callout.reasons.map((reason) => (
                  <List.Item key={reason}>{reason}</List.Item>
                ))}
              </List>
            )}

            <Stack gap={4}>
              <Text size="xs" fw={600}>
                Version for the video
              </Text>
              <SegmentedControl
                size="xs"
                value={callout.choice ?? AUTOMATIC}
                onChange={(value) =>
                  setChoice.mutate({
                    calloutId: callout.id,
                    engine:
                      value === AUTOMATIC
                        ? null
                        : (value as CalloutGraphicEngineKey),
                  })
                }
                disabled={setChoice.isPending}
                data={[
                  { value: AUTOMATIC, label: "Automatic" },
                  ...callout.engines.map((item) => ({
                    value: item.key,
                    label: item.label,
                  })),
                ]}
              />
            </Stack>

            <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
              {callout.engines.map((item) => (
                <VersionCard
                  key={item.key}
                  projectId={projectId}
                  callout={callout}
                  engine={item}
                />
              ))}
            </SimpleGrid>

            {mutationError && (
              <Text size="xs" c="red">
                {describeError(mutationError)}
              </Text>
            )}
            {idle && (
              <Group gap="xs">
                <Button
                  size="compact-xs"
                  onClick={() => make.mutate({ calloutId: callout.id })}
                  loading={make.isPending}
                  disabled={!callout.can_run}
                >
                  Make both versions
                </Button>
              </Group>
            )}
          </>
        )}
      </Stack>
    </Paper>
  );
}

/** One version of a callout: its preview, its latest attempt, and what can be done with it. */
function VersionCard({
  projectId,
  callout,
  engine,
}: {
  projectId: number;
  callout: CalloutGraphic;
  engine: CalloutGraphicEngine;
}) {
  const make = useMakeCalloutGraphic(projectId);
  const askAgain = useAskCalloutGraphicAgain(projectId);
  const busy = engine.status === "writing" || engine.status === "rendering";
  const attempt =
    engine.attempts.find((item) => item.url !== null) ?? engine.attempts[0];
  const warnings = warningsOf(attempt?.warnings);
  const mutationError = make.error ?? askAgain.error;
  const badge = ENGINE_BADGE[engine.status];
  const blocked =
    callout.blocked_reason !== null && callout.status !== "working";
  const idle = engine.status === "none" || engine.status === "out_of_date";
  const inUse = callout.used?.engine === engine.key;

  return (
    <Paper withBorder p="xs" radius="md" data-engine={engine.key}>
      <Stack gap="xs">
        <Group justify="space-between" gap="xs">
          <Text size="sm" fw={600}>
            {engine.label}
          </Text>
          <Group gap={6} wrap="nowrap">
            {inUse && (
              <Badge color="teal" variant="outline">
                In use
              </Badge>
            )}
            {busy && <Loader size="xs" />}
            <Badge color={badge.color} variant="light">
              {badge.label}
            </Badge>
          </Group>
        </Group>

        {attempt?.url ? (
          <video
            src={attempt.url}
            muted
            loop
            controls
            playsInline
            preload="metadata"
            style={{
              width: "100%",
              borderRadius: 4,
              background: "#808080",
            }}
          />
        ) : (
          <Text size="xs" c="dimmed">
            {busy ? "Being made" : "No preview yet"}
          </Text>
        )}

        {attempt !== undefined && (
          <Text size="xs" c="dimmed">
            Attempt {attempt.attempt}
            {engine.attempts.length > 1 ? ` of ${engine.attempts.length}` : ""}
            {attempt.url !== null && !attempt.current
              ? ", drawn for earlier words or colours"
              : ""}
            {attempt.repair_of !== null
              ? ", a repair of an earlier attempt"
              : ""}
          </Text>
        )}
        {warnings.map((warning) => (
          <Text
            key={warning}
            size="xs"
            c="yellow.8"
            style={{ wordBreak: "break-word" }}
          >
            {warning}
          </Text>
        ))}
        {engine.last_error !== null && (
          <Text size="xs" c="red" style={{ wordBreak: "break-word" }}>
            {engine.last_error}
          </Text>
        )}
        {mutationError && (
          <Text size="xs" c="red">
            {describeError(mutationError)}
          </Text>
        )}

        <Group gap="xs">
          {idle && (
            <Button
              size="compact-xs"
              onClick={() =>
                make.mutate({ calloutId: callout.id, engine: engine.key })
              }
              loading={make.isPending}
              disabled={busy || blocked}
            >
              Make
            </Button>
          )}
          <Button
            size="compact-xs"
            variant="default"
            onClick={() =>
              askAgain.mutate({ calloutId: callout.id, engine: engine.key })
            }
            loading={askAgain.isPending}
            disabled={busy || blocked}
            title="A paid model call: makes this version again as a new attempt."
          >
            Ask again
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}
