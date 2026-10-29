import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  ColorSwatch,
  Group,
  List,
  Loader,
  Paper,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import {
  useCalloutPlan,
  useCalloutPlanVersion,
  useRunCalloutPlan,
  useSaveCalloutPlan,
  type Callout,
  type CalloutPlanOut,
  type CalloutRole,
  type CalloutScriptLine,
} from "../../api/calloutPlan";
import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { CalloutPlanEditor } from "./CalloutPlanEditor";
import { ReplaceManualModal } from "./ReplaceManualModal";
import { ROLE_LABELS, TYPE_LABELS, formatClock, roleColour } from "./calloutPlanView";

type CalloutPlanPanelProps = {
  projectId: number;
};

/**
 * The callout plan stage of an explainer: the accent colour, and each callout in order with its
 * type, text, colour role, the line it sits on, an on or off state and any warning. Run / Re-run
 * writes a new version from the model; Edit saves one written by you (text, type, colour, on or
 * off). Only the callouts that are on go to the render.
 */
export function CalloutPlanPanel({ projectId }: CalloutPlanPanelProps) {
  const { data, isLoading, isError, error } = useCalloutPlan(projectId);
  const run = useRunCalloutPlan(projectId);
  const save = useSaveCalloutPlan(projectId);
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  // The version the user picked. Until they pick one, the newest is shown.
  const [picked, setPicked] = useState<number | null>(null);

  const latest = data?.latest ?? null;
  const shownVersion = picked ?? latest?.version ?? null;
  const viewingOlder = latest !== null && shownVersion !== latest.version;
  const olderVersion = useCalloutPlanVersion(projectId, viewingOlder ? shownVersion : null);
  const shown = viewingOlder ? (olderVersion.data ?? null) : latest;

  const job = data?.job ?? null;
  const active = isJobActive(job);
  const notWanted = data !== undefined && !data.wanted;
  const blocked = data?.blocked_reason ?? null;

  const startRun = (confirmReplaceManual: boolean) => {
    // A new version is on its way: show it when it arrives.
    setPicked(null);
    run.mutate({ confirmReplaceManual });
  };

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>Callout plan</Title>
              <Text size="sm" c="dimmed">
                Short pieces of text shown on the picture to keep the viewer watching: a hook
                question, the key idea, the big number. The model suggests them, and you review
                them here before the video is made.
              </Text>
            </Stack>
            <Group gap="sm" align="flex-end">
              {data && data.versions.length > 1 && (
                <Select
                  aria-label="Version"
                  w={190}
                  allowDeselect={false}
                  data={data.versions.map((version, index) => ({
                    value: String(version.version),
                    label: `Version ${version.version}${index === 0 ? " (newest)" : ""}`,
                  }))}
                  value={shownVersion === null ? null : String(shownVersion)}
                  onChange={(value) => value !== null && setPicked(Number(value))}
                />
              )}
              <Button
                variant="default"
                onClick={() => {
                  save.reset();
                  setPicked(null);
                  setEditing(true);
                }}
                disabled={
                  notWanted ||
                  editing ||
                  latest === null ||
                  latest.content.callouts.length === 0 ||
                  active ||
                  blocked !== null ||
                  data?.out_of_date === true
                }
              >
                Edit
              </Button>
              <Button
                onClick={() => (data?.needs_confirmation ? setConfirming(true) : startRun(false))}
                loading={run.isPending || active}
                disabled={isLoading || isError || editing || notWanted || blocked !== null}
              >
                {latest ? "Re-run" : "Run"}
              </Button>
            </Group>
          </Group>

          {blocked !== null && (
            <Text size="sm" c="dimmed">
              {blocked}
            </Text>
          )}
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the callout plan">
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title="Could not start the callout plan">
              {describeError(run.error)}
            </Alert>
          )}
          {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
          {job?.status === "failed" && (
            <Alert color="red" title="The last run failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
          {data?.out_of_date && !viewingOlder && !notWanted && (
            <Alert color="yellow" title="Out of date">
              <Stack gap={4}>
                <Text size="sm">
                  Something this plan was written from has changed. Press Re-run to write a new
                  one. Until then it cannot be edited.
                </Text>
                {data.reasons.length > 0 && (
                  <List size="sm">
                    {data.reasons.map((reason) => (
                      <List.Item key={reason}>{reason}</List.Item>
                    ))}
                  </List>
                )}
              </Stack>
            </Alert>
          )}
        </Stack>
      </Paper>

      {editing && latest && data && (
        <Paper withBorder p="md" radius="md">
          <CalloutPlanEditor
            initial={latest.content.callouts}
            script={data.script}
            saving={save.isPending}
            error={save.error}
            onSave={(content) => save.mutate(content, { onSuccess: () => setEditing(false) })}
            onCancel={() => setEditing(false)}
          />
        </Paper>
      )}
      {shown && !editing && <CalloutPlanView plan={shown} script={data?.script ?? []} />}
      {viewingOlder && olderVersion.isError && (
        <Alert color="red" title="Could not load the version">
          {describeError(olderVersion.error)}
        </Alert>
      )}
      <ReplaceManualModal
        opened={confirming}
        title="Run the callout plan again?"
        what="The newest callout plan"
        confirmLabel="Re-run"
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          startRun(true);
        }}
      />
    </Stack>
  );
}

function sourceLabel(source: string) {
  return source === "manual" ? "written by you" : "written by the model";
}

function RoleBadge({ role, accent }: { role: CalloutRole; accent: string }) {
  return (
    <Group gap={4} wrap="nowrap">
      <ColorSwatch color={roleColour(role, accent)} size={14} />
      <Text size="xs" c="dimmed">
        {ROLE_LABELS[role]}
      </Text>
    </Group>
  );
}

function CalloutTexts({ callout, accent }: { callout: Callout; accent: string }) {
  if (callout.type === "comparison" && callout.sides) {
    return (
      <Group gap="md">
        {callout.sides.map((side, index) => (
          <Group key={index} gap={6} wrap="nowrap">
            <ColorSwatch color={roleColour(side.role, accent)} size={14} />
            <Text fw={600}>{side.text}</Text>
          </Group>
        ))}
      </Group>
    );
  }
  if (callout.type === "list" && callout.items) {
    return (
      <List size="sm" withPadding>
        {callout.items.map((item, index) => (
          <List.Item key={index}>
            <Text fw={600} span>
              {item.text}
            </Text>
          </List.Item>
        ))}
      </List>
    );
  }
  return <Text fw={600}>{callout.text}</Text>;
}

function CalloutPlanView({ plan, script }: { plan: CalloutPlanOut; script: CalloutScriptLine[] }) {
  const { accent, callouts } = plan.content;
  const on = callouts.filter((callout) => callout.enabled).length;
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Group gap="xs" align="center">
            <ColorSwatch color={accent.colour} size={20} />
            <Stack gap={0}>
              <Text size="sm" fw={500}>
                Accent colour {accent.colour}
              </Text>
              {accent.reason && (
                <Text size="xs" c="dimmed">
                  {accent.reason}
                </Text>
              )}
            </Stack>
          </Group>
          <Text size="xs" c="dimmed">
            Version {plan.version}, {sourceLabel(plan.source)}. {on} of {callouts.length} callouts
            on.
          </Text>
        </Group>
        {accent.note && (
          <Alert color="yellow" title="Accent colour changed">
            {accent.note}
          </Alert>
        )}
        {callouts.length === 0 && (
          <Text size="sm" c="dimmed">
            The model found nothing worth a callout in this script.
          </Text>
        )}
        {callouts.map((callout, index) => {
          const line = script.find(
            (item) => item.scene_id === callout.scene_id && item.unit_id === callout.unit_id,
          );
          return (
            <Paper
              key={callout.id}
              withBorder
              p="sm"
              radius="md"
              style={{ opacity: callout.enabled ? 1 : 0.55 }}
            >
              <Stack gap={4}>
                <Group gap="sm" justify="space-between">
                  <Group gap="sm">
                    <Text size="sm" c="dimmed">
                      {index + 1}.
                    </Text>
                    <Badge variant="light">{TYPE_LABELS[callout.type]}</Badge>
                    {callout.role && <RoleBadge role={callout.role} accent={accent.colour} />}
                    {!callout.enabled && (
                      <Badge color="gray" variant="outline">
                        Off
                      </Badge>
                    )}
                  </Group>
                  <Text size="xs" c="dimmed">
                    About {formatClock(callout.estimated_start_s)}
                    {line ? ` · ${line.scene_title}` : ""}
                  </Text>
                </Group>
                <CalloutTexts callout={callout} accent={accent.colour} />
                <Text size="xs" c="dimmed">
                  On: “{callout.phrase}”
                </Text>
                {callout.warnings.map((warning) => (
                  <Text key={warning} size="xs" c="orange">
                    {warning}
                  </Text>
                ))}
              </Stack>
            </Paper>
          );
        })}
      </Stack>
    </Paper>
  );
}
