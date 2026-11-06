import { useState } from "react";
import {
  Alert,
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
import { useCalloutLook, useRunCalloutLook, type CalloutLookOut } from "../../api/calloutLook";
import { isJobActive } from "../../api/polling";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { FeedbackBadge } from "./FeedbackBadge";
import { FeedbackModal } from "./FeedbackModal";

type CalloutLookCardProps = {
  projectId: number;
};

const PANEL_LABELS: Record<string, string> = {
  none: "No panel",
  card: "Card",
  glass: "Glass",
  underline: "Underline",
  ribbon: "Ribbon",
};

const CORNER_LABELS: Record<string, string> = {
  sharp: "Sharp",
  soft: "Soft",
  round: "Round",
};

const ENTRANCE_LABELS: Record<string, string> = {
  fade_up: "Fade up",
  wipe: "Wipe",
  pop: "Pop",
  draw: "Draw",
};

const DENSITY_LABELS: Record<string, string> = {
  airy: "Airy",
  balanced: "Balanced",
  compact: "Compact",
};

/**
 * The callout look of a motion explainer: the one look every motion callout of the video shares
 * (the panel, the corners, how a callout enters, how a number stands out). The model writes it
 * from the graphics look and the Story Bible. Nothing is shown for a project that does not draw
 * its callouts as motion graphics.
 */
export function CalloutLookCard({ projectId }: CalloutLookCardProps) {
  const { data, isLoading, isError, error } = useCalloutLook(projectId);
  const run = useRunCalloutLook(projectId);
  const [noting, setNoting] = useState(false);

  if (data !== undefined && !data.wanted) {
    return null;
  }

  const latest = data?.latest ?? null;
  const job = data?.job ?? null;
  const active = isJobActive(job);
  const blocked = data?.blocked_reason ?? null;
  const cannotRun = isLoading || isError || blocked !== null;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Callout look</Title>
            <Text size="sm" c="dimmed">
              The one look every motion callout of this video shares: the panel behind it, the
              corners, how it enters and how a number stands out. The model writes it from the
              graphics look and the Story Bible.
            </Text>
          </Stack>
          <Group gap="sm" align="flex-end">
            <Button
              variant="default"
              onClick={() => setNoting(true)}
              disabled={cannotRun || latest === null || active}
            >
              Write again with a note
            </Button>
            <Button
              onClick={() => run.mutate({})}
              loading={run.isPending || active}
              disabled={cannotRun}
            >
              {latest ? "Write again" : "Run"}
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
          <Alert color="red" title="Could not load the callout look">
            {describeError(error)}
          </Alert>
        )}
        {run.isError && (
          <Alert color="red" title="Could not start the callout look">
            {describeError(run.error)}
          </Alert>
        )}
        {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
        {job?.status === "failed" && (
          <Alert color="red" title="The last run failed">
            {job.error ?? "The job failed."}
          </Alert>
        )}
        {data?.out_of_date && (
          <Alert color="yellow" title="Out of date">
            <Stack gap={4}>
              <Text size="sm">
                Something this look was written from has changed. Press Write again to make a new
                one.
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

        {latest && <CalloutLookView look={latest} />}
      </Stack>

      <FeedbackModal
        opened={noting}
        title="Feedback on the callout look"
        what="the callout look"
        initialText={latest?.feedback ?? ""}
        writtenByUser={false}
        submitLabel="Write with feedback"
        onCancel={() => setNoting(false)}
        onSubmit={(text) => {
          setNoting(false);
          run.mutate({ feedback: text });
        }}
      />
    </Paper>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm" fw={500}>
        {value}
      </Text>
    </Stack>
  );
}

function CalloutLookView({ look }: { look: CalloutLookOut }) {
  const fields = look.content.look;
  return (
    <Stack gap="sm">
      <Group gap="xs">
        <Text size="xs" c="dimmed">
          Version {look.version}, written by the model.
        </Text>
        <FeedbackBadge text={look.feedback} />
      </Group>

      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
        <Detail label="Panel" value={PANEL_LABELS[fields.panel] ?? fields.panel} />
        <Detail label="Corners" value={CORNER_LABELS[fields.corners] ?? fields.corners} />
        <Detail label="Entrance" value={ENTRANCE_LABELS[fields.entrance] ?? fields.entrance} />
        <Detail label="Density" value={DENSITY_LABELS[fields.density] ?? fields.density} />
      </SimpleGrid>

      <Detail label="Emphasis" value={fields.emphasis} />
      <Detail label="Notes" value={fields.notes} />
      <Text size="sm">{look.content.reason}</Text>
    </Stack>
  );
}
