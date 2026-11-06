import {
  Alert,
  Badge,
  Button,
  Group,
  List,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import {
  useAskCalloutGraphicAgain,
  useCalloutGraphics,
  useMakeCalloutGraphic,
  useMakeCalloutGraphics,
  type CalloutGraphic,
  type CalloutGraphicEngine,
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

/**
 * The generated component of every callout of a motion explainer, with a preview of each (the
 * callout on a grey backdrop). The model writes one component per callout from the callout look;
 * a component that fails its checks is repaired, and one that cannot be repaired leaves the
 * callout as a text box. Nothing is shown for a project that does not draw its callouts as motion
 * graphics.
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
              Each callout that is turned on gets an animated component written
              by the model in the callout look, with a preview you can watch
              here. Every callout costs a model call.
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

function CalloutRow({
  projectId,
  callout,
}: {
  projectId: number;
  callout: CalloutGraphic;
}) {
  const make = useMakeCalloutGraphic(projectId);
  const askAgain = useAskCalloutGraphicAgain(projectId);
  const engine = callout.engines[0];
  const busy =
    engine !== undefined &&
    (engine.status === "writing" || engine.status === "rendering");
  const attempt =
    engine?.attempts.find((item) => item.url !== null) ?? engine?.attempts[0];
  const warnings = warningsOf(attempt?.warnings);
  const mutationError = make.error ?? askAgain.error;
  const idle = callout.status === "none" || callout.status === "out_of_date";

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
          </Stack>
          {engine === undefined ? (
            <Badge color="gray" variant="light">
              Off
            </Badge>
          ) : (
            <Group gap={6} wrap="nowrap">
              {busy && <Loader size="xs" />}
              <Badge color={ENGINE_BADGE[engine.status].color} variant="light">
                {ENGINE_BADGE[engine.status].label}
              </Badge>
            </Group>
          )}
        </Group>

        {engine !== undefined && (
          <>
            {callout.used?.engine === "box" && (
              <Alert
                color="orange"
                p="xs"
                title="This callout will be a text box"
              >
                Its component failed after its repairs, and nothing more will be
                tried for it. Ask again to try a new one.
              </Alert>
            )}
            {callout.reasons.length > 0 && (
              <List size="xs">
                {callout.reasons.map((reason) => (
                  <List.Item key={reason}>{reason}</List.Item>
                ))}
              </List>
            )}

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
                  maxWidth: 480,
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
                {engine.attempts.length > 1
                  ? ` of ${engine.attempts.length}`
                  : ""}
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
                  onClick={() => make.mutate({ calloutId: callout.id })}
                  loading={make.isPending}
                  disabled={!callout.can_run}
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
                disabled={
                  busy ||
                  (callout.blocked_reason !== null &&
                    callout.status !== "working")
                }
                title="A paid model call: makes this component again as a new attempt."
              >
                Ask again
              </Button>
            </Group>
          </>
        )}
      </Stack>
    </Paper>
  );
}
