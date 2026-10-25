import { Link } from "react-router";
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

import { describeError } from "../../api/errors";
import {
  useAuditMusicCues,
  useMusicCues,
  useRunMusicCues,
  type MusicCueDetail,
  type MusicCueEntry,
  type MusicCueItem,
  type MusicCueWording,
  type MusicCuesAudit,
} from "../../api/musicCues";
import { useMusicPlan, type MusicPlanAnchor, type MusicPlanTimeline } from "../../api/musicPlan";
import { isJobActive } from "../../api/polling";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import {
  KIND_COLORS,
  KIND_LABELS,
  MAKER_LABELS,
  cueTimes,
  describeAnchor,
  formatSeconds,
} from "./musicPlanView";

type MusicCuesPanelProps = {
  projectId: number;
};

/** Fields the server needs that say nothing about how the music sounds. */
const HIDDEN_FIELDS = new Set(["instrumental", "lyrics", "vocal_language"]);
/** The field that holds the wording itself, by music model. */
const TEXT_FIELDS = ["caption", "prompt"];

/**
 * The music cues stage: for each cue of the newest plan, its exact detail (the order of moods
 * in words, the anchors in seconds, the fades, the mix notes and the hits it asked for), the
 * prompts that will be generated for it with their warnings, and any objection it raised to
 * the plan. Then what the audit of all prompts found. Run details the cues that have none; the
 * plan is only sent back for a revision by the story pipeline. When music is switched off, the
 * panel only says so.
 */
export function MusicCuesPanel({ projectId }: MusicCuesPanelProps) {
  const { data, isLoading, isError, error } = useMusicCues(projectId);
  const plan = useMusicPlan(projectId);
  const run = useRunMusicCues(projectId);
  const audit = useAuditMusicCues(projectId);

  const timeline = plan.data?.latest?.timeline ?? null;
  const musicOff = data !== undefined && !data.music_enabled;
  const blocked = data?.blocked_reason ?? null;
  const cues = data?.cues ?? [];
  const anyRunning = cues.some((entry) => entry.active || isJobActive(entry.job));
  const busy = anyRunning || (data?.audit_active ?? false) || (data?.revision_active ?? false);
  const needsRun = cues.some((entry) => entry.makes_audio && !entry.done);
  const everyCueDetailed = cues.every((entry) => !entry.makes_audio || (entry.done && entry.row));
  const objections = cues.filter((entry) => entry.waiting_for_revision);

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>Music cues</Title>
              <Text size="sm" c="dimmed">
                Each cue of the plan is detailed against the story, then written as several prompts
                for its music model. A cue that cannot work as planned says so. An audit then reads
                every prompt together against the Music Bible.
              </Text>
            </Stack>
            <Group gap="sm">
              <Button
                variant="default"
                onClick={() => audit.mutate()}
                loading={audit.isPending || (data?.audit_active ?? false)}
                disabled={
                  isLoading ||
                  isError ||
                  musicOff ||
                  blocked !== null ||
                  busy ||
                  !everyCueDetailed ||
                  objections.length > 0 ||
                  !cues.some((entry) => entry.makes_audio)
                }
              >
                {data?.audit ? "Audit again" : "Audit"}
              </Button>
              <Button
                onClick={() => run.mutate({})}
                loading={run.isPending || anyRunning}
                disabled={isLoading || isError || musicOff || blocked !== null || !needsRun}
              >
                {cues.some((entry) => entry.row) ? "Detail the rest" : "Detail the cues"}
              </Button>
            </Group>
          </Group>

          {!musicOff && blocked !== null && (
            <Text size="sm" c="dimmed">
              {blocked}
            </Text>
          )}
          {musicOff && (
            <Alert color="gray" title="Music is switched off">
              This project is made without music, so this step is skipped. Turn music on in the{" "}
              <Link to={`/projects/${projectId}/settings`}>project settings</Link> to detail it.
            </Alert>
          )}
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the music cues">
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title="Could not start the cue details">
              {describeError(run.error)}
            </Alert>
          )}
          {audit.isError && (
            <Alert color="red" title="Could not start the audit">
              {describeError(audit.error)}
            </Alert>
          )}
          {data?.audit_job && data.audit_job.status !== "succeeded" && (
            <Group gap="xs">
              <Text size="sm">Audit:</Text>
              <JobStatusBadge job={data.audit_job} />
            </Group>
          )}
          {data?.audit_job?.status === "failed" && (
            <Alert color="red" title="The last audit failed">
              {data.audit_job.error ?? "The job failed."}
            </Alert>
          )}
          {data && objections.length > 0 && (
            <Alert color="yellow" title="Cues object to the plan">
              <Stack gap={4}>
                <Text size="sm">
                  {objections.length} cue{objections.length === 1 ? "" : "s"} say the plan cannot
                  work for them. Run the story pipeline to revise the plan from these objections (
                  {data.revisions_used} of {data.revisions_allowed} revisions used).
                </Text>
              </Stack>
            </Alert>
          )}
        </Stack>
      </Paper>

      {data?.audit && <AuditView audit={data.audit} />}

      {cues.length > 0 && (
        <Paper withBorder p="md" radius="md">
          <Stack gap="md">
            {cues.map((entry) => (
              <CueEntry
                key={entry.cue.id}
                entry={entry}
                timeline={timeline}
                running={run.isPending || busy}
                onRun={() => run.mutate({ cueId: entry.cue.id })}
              />
            ))}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}

function AuditView({ audit }: { audit: MusicCuesAudit }) {
  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap={4}>
        <Group gap="xs">
          <Title order={5}>The audit</Title>
          <Badge size="sm" variant="light" color={audit.verdict === "ok" ? "green" : "yellow"}>
            {audit.verdict === "ok" ? "Fine" : `${audit.fixes.length} fixed`}
          </Badge>
          {!audit.current && (
            <Badge size="sm" variant="light" color="orange">
              Older than the prompts
            </Badge>
          )}
        </Group>
        {audit.fixes.length > 0 && (
          <List size="sm">
            {audit.fixes.map((fix) => (
              <List.Item key={`${fix.item}-${fix.wording}`}>
                <b>
                  {fix.item}, wording {fix.wording}:
                </b>{" "}
                {fix.problem}
              </List.Item>
            ))}
          </List>
        )}
      </Stack>
    </Paper>
  );
}

function statusBadge(entry: MusicCueEntry) {
  if (!entry.makes_audio) return { color: "gray", label: "Nothing to write" };
  if (entry.active) return { color: "blue", label: "Writing" };
  if (entry.waiting_for_revision) return { color: "yellow", label: "Waiting for the plan" };
  if (entry.out_of_date) return { color: "orange", label: "Out of date" };
  if (entry.done) return { color: "green", label: "Done" };
  if (entry.job?.status === "failed") return { color: "red", label: "Failed" };
  return { color: "gray", label: "Not detailed" };
}

function CueEntry({
  entry,
  timeline,
  running,
  onRun,
}: {
  entry: MusicCueEntry;
  timeline: MusicPlanTimeline | null;
  running: boolean;
  onRun: () => void;
}) {
  const { cue, row } = entry;
  const status = statusBadge(entry);
  return (
    <Stack gap={4}>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Group gap="xs" wrap="nowrap" align="flex-start">
          <Badge size="sm" variant="light" color={KIND_COLORS[cue.kind] ?? "gray"}>
            {KIND_LABELS[cue.kind] ?? cue.kind}
          </Badge>
          <Text size="sm">
            <b>{cue.id}</b>
            {cue.maker ? ` (${MAKER_LABELS[cue.maker] ?? cue.maker})` : ""}, {cueTimes(cue)}:{" "}
            {cue.summary}
          </Text>
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Badge size="sm" variant="light" color={status.color}>
            {status.label}
          </Badge>
          {entry.makes_audio && (
            <Button size="compact-xs" variant="default" disabled={running} onClick={onRun}>
              {row ? "Detail again" : "Detail"}
            </Button>
          )}
        </Group>
      </Group>

      {entry.job && entry.job.status !== "succeeded" && <JobStatusBadge job={entry.job} />}
      {entry.job?.status === "failed" && (
        <Text size="xs" c="red">
          {entry.job.error ?? "The job failed."}
        </Text>
      )}
      {entry.blocked_reason && !entry.done && (
        <Text size="xs" c="dimmed">
          {entry.blocked_reason}
        </Text>
      )}
      {entry.out_of_date && (
        <List size="xs" c="orange">
          {entry.reasons.map((reason) => (
            <List.Item key={reason}>{reason}</List.Item>
          ))}
        </List>
      )}
      {!entry.makes_audio && (
        <Text size="xs" c="dimmed">
          {cue.kind === "silence"
            ? "A silence: nothing is generated."
            : "A sound H3 makes from the video: nothing is written here."}
        </Text>
      )}

      {row?.pushback && (
        <Alert color={row.pushback.sent ? "yellow" : "gray"} title="Objection to the plan" p="xs">
          <Text size="xs">
            {row.pushback.problem} {row.pushback.suggestion}
          </Text>
          <Text size="xs" c="dimmed">
            {row.pushback.sent
              ? "The plan is sent back for a revision."
              : "No revision is left, so the cue was written as planned."}
          </Text>
        </Alert>
      )}
      {row && <DetailView detail={row.detail} timeline={timeline} />}
      {row?.items.map((item) => (
        <ItemView key={item.id} item={item} />
      ))}
    </Stack>
  );
}

function anchorText(timeline: MusicPlanTimeline | null, anchor: MusicPlanAnchor): string {
  const when = formatSeconds(anchor.seconds);
  return timeline ? `${describeAnchor(timeline, anchor)} (${when})` : when;
}

function DetailView({
  detail,
  timeline,
}: {
  detail: MusicCueDetail;
  timeline: MusicPlanTimeline | null;
}) {
  const order = (detail.internal_order ?? []).map((step) => step.mood);
  return (
    <Stack gap={2}>
      {detail.description && <Text size="xs">{detail.description}</Text>}
      {detail.at && <Text size="xs">At {anchorText(timeline, detail.at)}.</Text>}
      {detail.start && detail.end && (
        <Text size="xs">
          From {anchorText(timeline, detail.start)} to {anchorText(timeline, detail.end)}
          {detail.span_s != null ? `, ${detail.span_s.toFixed(1)} s.` : "."}
        </Text>
      )}
      {order.length > 0 && <Text size="xs">Order: {order.join(", then ")}.</Text>}
      {(detail.fade_in_s != null || detail.fade_out_s != null) && (
        <Text size="xs">
          {detail.fade_in_s != null ? `Fade in ${detail.fade_in_s} s. ` : ""}
          {detail.fade_out_s != null ? `Fade out ${detail.fade_out_s} s.` : ""}
        </Text>
      )}
      <Text size="xs">
        Under the voice: {detail.mix.under_voice}
        {detail.mix.swell_in_gaps ? ", swells in the gaps" : ""}.
        {detail.mix.notes ? ` ${detail.mix.notes}` : ""}
      </Text>
      {(detail.hit_requests ?? []).map((hit) => (
        <Text key={hit.id} size="xs">
          Hit {hit.id} at {anchorText(timeline, hit.at)}: {hit.description}
        </Text>
      ))}
    </Stack>
  );
}

function ItemView({ item }: { item: MusicCueItem }) {
  return (
    <Stack gap={2} pl="sm">
      <Group gap="xs">
        <Text size="sm" fw={600}>
          {item.role === "hit" ? `Hit ${item.id}` : "Prompts"}
        </Text>
        <Text size="xs" c="dimmed">
          {item.model}
          {item.requested_s != null ? `, ${item.requested_s.toFixed(1)} s asked for` : ""}
          {item.length_capped ? " (cut to the model's longest)" : ""}
        </Text>
      </Group>
      {item.theme && (
        <Text size="xs" c="dimmed">
          Theme: {String(item.theme.name ?? item.theme.theme_id)}, built from the{" "}
          {item.theme.based_on === "version" ? "recording for this emotion" : "canonical recording"}
          ; tempo, key and time signature are fixed.
        </Text>
      )}
      {item.wordings.map((wording, index) => (
        <WordingView key={index} wording={wording} place={index + 1} />
      ))}
    </Stack>
  );
}

function WordingView({ wording, place }: { wording: MusicCueWording; place: number }) {
  const textKey = TEXT_FIELDS.find((key) => typeof wording.fields[key] === "string");
  const others = Object.entries(wording.fields).filter(
    ([key]) => key !== textKey && !HIDDEN_FIELDS.has(key),
  );
  return (
    <Stack gap={0}>
      <Text size="xs">
        <b>{place}.</b> {textKey ? String(wording.fields[textKey]) : "(no text)"}
      </Text>
      {others.length > 0 && (
        <Text size="xs" c="dimmed">
          {others.map(([key, value]) => `${key}: ${String(value)}`).join(", ")}
        </Text>
      )}
      {wording.warnings.map((warning) => (
        <Text key={warning} size="xs" c="orange">
          {warning}
        </Text>
      ))}
      {wording.audit && (
        <Text size="xs" c="blue">
          Fixed by the audit: {wording.audit.problem}
        </Text>
      )}
    </Stack>
  );
}
