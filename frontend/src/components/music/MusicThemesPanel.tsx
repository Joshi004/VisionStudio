import { useState } from "react";
import { Link } from "react-router";
import {
  Alert,
  Badge,
  Button,
  Group,
  List,
  Loader,
  Modal,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useChooseThemeCandidate,
  useMusicThemes,
  useRegenerateThemeVersion,
  useRunMusicThemes,
  type MusicThemeEntry,
  type ThemeCandidate,
  type ThemeCheck,
  type ThemeVersion,
} from "../../api/musicThemes";
import type { LabMusicRun } from "../../api/musicLab";
import { isJobActive } from "../../api/polling";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { Measurements } from "../musicLab/MusicRunRating";

type MusicThemesPanelProps = {
  projectId: number;
};

/**
 * The themes of the Music Bible, recorded: several candidates of each, the one chosen as its
 * canonical recording, and a version for each emotion. Recording starts only from the buttons
 * here or from a pipeline run. When music is switched off the panel only says so.
 */
export function MusicThemesPanel({ projectId }: MusicThemesPanelProps) {
  const { data, isLoading, isError, error } = useMusicThemes(projectId);
  const run = useRunMusicThemes(projectId);
  // What the confirmation is for: every theme (`all`) or one theme id. None when closed.
  const [confirming, setConfirming] = useState<{ themeId?: string } | null>(null);

  const musicOff = data !== undefined && !data.music_enabled;
  const blocked = data?.blocked_reason ?? null;
  const themes = data?.themes ?? [];
  const anyActive = themes.some((theme) => theme.active);
  const anyWork = themes.some((theme) => theme.action !== null && !theme.active);

  const start = (themeId: string | undefined, confirmReplaceOwner: boolean) => {
    run.mutate({ themeId, confirmReplaceOwner });
  };
  const ask = (themeId: string | undefined) => {
    const targets = themes.filter((theme) => themeId === undefined || theme.theme_id === themeId);
    if (targets.some((theme) => theme.needs_confirmation)) {
      setConfirming({ themeId });
    } else {
      start(themeId, false);
    }
  };

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>Music themes</Title>
              <Text size="sm" c="dimmed">
                Each theme of the Music Bible is recorded as a few candidates. The one you or the
                checks choose is its canonical recording; a version of it is then made for each
                emotion.
              </Text>
            </Stack>
            <Button
              onClick={() => ask(undefined)}
              loading={run.isPending || anyActive}
              disabled={isLoading || isError || musicOff || blocked !== null || !anyWork}
            >
              Record the themes
            </Button>
          </Group>

          {musicOff && (
            <Alert color="gray" title="Music is switched off">
              This project is made without music, so this step is skipped. Turn music on in the{" "}
              <Link to={`/projects/${projectId}/settings`}>project settings</Link> to record the
              themes.
            </Alert>
          )}
          {!musicOff && blocked !== null && (
            <Text size="sm" c="dimmed">
              {blocked}
            </Text>
          )}
          {data && !musicOff && blocked === null && (
            <Text size="xs" c="dimmed">
              {data.candidates_per_theme} candidates of {data.duration_s} s for each theme. Both can
              be changed in the settings.
            </Text>
          )}
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the music themes">
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title="Could not start the themes">
              {describeError(run.error)}
            </Alert>
          )}
        </Stack>
      </Paper>

      {themes.map((theme) => (
        <ThemeCard
          key={theme.theme_id}
          projectId={projectId}
          theme={theme}
          onRecord={() => ask(theme.theme_id)}
          recording={run.isPending}
        />
      ))}

      <Modal
        opened={confirming !== null}
        onClose={() => setConfirming(null)}
        title="Record the themes again?"
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            A theme you chose the recording of has changed. Recording it again makes new candidates
            and replaces your choice once one is chosen. The earlier recordings stay in the Music
            lab.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
            <Button
              color="red"
              onClick={() => {
                const themeId = confirming?.themeId;
                setConfirming(null);
                start(themeId, true);
              }}
            >
              Record again
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

type ThemeCardProps = {
  projectId: number;
  theme: MusicThemeEntry;
  onRecord: () => void;
  recording: boolean;
};

function statusBadge(theme: MusicThemeEntry) {
  if (theme.active) {
    return <Badge color="blue">Recording</Badge>;
  }
  if (theme.done) {
    return <Badge color="green">Done</Badge>;
  }
  if (theme.out_of_date) {
    return <Badge color="yellow">Out of date</Badge>;
  }
  if (theme.version === null) {
    return <Badge color="gray">Not recorded</Badge>;
  }
  return <Badge color="orange">Incomplete</Badge>;
}

function recordLabel(theme: MusicThemeEntry) {
  if (theme.action === "versions") {
    return "Make the versions";
  }
  if (theme.action === "candidates") {
    return "Record more candidates";
  }
  return theme.version === null ? "Record" : "Record again";
}

function fieldsLine(fields: MusicThemeEntry["fields"]) {
  if (fields === null) {
    return "";
  }
  const parts = [
    fields.bpm !== undefined ? `${String(fields.bpm)} bpm` : null,
    typeof fields.keyscale === "string" ? fields.keyscale : null,
    fields.time_signature !== undefined ? `${String(fields.time_signature)} time` : null,
    fields.duration !== undefined ? `${String(fields.duration)} s` : null,
  ];
  return parts.filter((part) => part !== null).join(", ");
}

function ThemeCard({ projectId, theme, onRecord, recording }: ThemeCardProps) {
  const choose = useChooseThemeCandidate(projectId);
  const regenerate = useRegenerateThemeVersion(projectId);
  const job = theme.job;
  const caption = typeof theme.fields?.caption === "string" ? theme.fields.caption : null;
  const recorded = new Set(theme.versions.map((version) => version.emotion));
  const missing = theme.emotions.filter((emotion) => !recorded.has(emotion));

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Group gap="xs">
              <Title order={5}>{theme.name}</Title>
              {theme.main && <Badge size="sm">Main theme</Badge>}
              {statusBadge(theme)}
            </Group>
            <Text size="sm">
              Stands for {theme.stands_for.kind}: {theme.stands_for.description}
            </Text>
            <Text size="xs" c="dimmed">
              {theme.signature_instrument}
              {theme.emotions.length > 0 ? `. Feels: ${theme.emotions.join(", ")}` : ""}
            </Text>
          </Stack>
          <Button
            variant="default"
            size="xs"
            onClick={onRecord}
            loading={recording}
            disabled={theme.active || theme.action === null}
          >
            {recordLabel(theme)}
          </Button>
        </Group>

        {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
        {job?.status === "failed" && (
          <Alert color="red" title="The last prompt job failed">
            {job.error ?? "The job failed."}
          </Alert>
        )}
        {theme.out_of_date && (
          <Alert color="yellow" title="Out of date">
            <List size="sm">
              {theme.reasons.map((reason) => (
                <List.Item key={reason}>{reason}</List.Item>
              ))}
            </List>
          </Alert>
        )}

        {caption !== null && (
          <details>
            <summary style={{ cursor: "pointer", fontSize: "var(--mantine-font-size-xs)" }}>
              What was sent: {fieldsLine(theme.fields)}
            </summary>
            <Text size="xs" mt={4} style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {caption}
            </Text>
          </details>
        )}

        {theme.candidates.length > 0 && (
          <Stack gap="xs">
            <Text size="xs" fw={700} c="dimmed" tt="uppercase">
              Candidates
              {theme.chosen_by !== null && (
                <> (chosen {theme.chosen_by === "owner" ? "by you" : "by the checks"})</>
              )}
            </Text>
            <SimpleGrid cols={{ base: 1, md: 2 }}>
              {theme.candidates.map((candidate) => (
                <CandidateCard
                  key={candidate.id}
                  candidate={candidate}
                  busy={theme.active || choose.isPending}
                  onChoose={() =>
                    choose.mutate({ themeId: theme.theme_id, candidateId: candidate.id })
                  }
                />
              ))}
            </SimpleGrid>
            {choose.isError && (
              <Alert color="red" title="Could not choose the recording">
                {describeError(choose.error)}
              </Alert>
            )}
          </Stack>
        )}

        {(theme.versions.length > 0 || missing.length > 0) && theme.chosen_candidate_id !== null && (
          <Stack gap="xs">
            <Text size="xs" fw={700} c="dimmed" tt="uppercase">
              Emotional versions
            </Text>
            <SimpleGrid cols={{ base: 1, md: 2 }}>
              {theme.versions.map((version) => (
                <VersionCard
                  key={version.id}
                  version={version}
                  busy={theme.active || regenerate.isPending}
                  onRegenerate={() =>
                    regenerate.mutate({ themeId: theme.theme_id, emotion: version.emotion })
                  }
                />
              ))}
              {missing.map((emotion) => (
                <Paper key={emotion} withBorder p="sm" radius="md">
                  <Text size="sm" fw={600}>
                    {emotion}
                  </Text>
                  <Text size="xs" c="dimmed">
                    Not recorded yet.
                  </Text>
                </Paper>
              ))}
            </SimpleGrid>
            {regenerate.isError && (
              <Alert color="red" title="Could not make the version again">
                {describeError(regenerate.error)}
              </Alert>
            )}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}

/** The player, or why there is none yet. */
function Recording({ run }: { run: LabMusicRun | null }) {
  if (run === null) {
    return null;
  }
  if (run.url !== null) {
    return <audio controls preload="none" src={run.url} style={{ width: "100%" }} />;
  }
  if (isJobActive(run.job)) {
    return (
      <Text size="xs" c="dimmed">
        Waiting for the sound. This page updates by itself.
      </Text>
    );
  }
  if (run.job?.status === "failed") {
    return (
      <Alert color="red" p="xs" title="The recording failed">
        <Text size="xs" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {run.job.error ?? "The job failed."}
        </Text>
      </Alert>
    );
  }
  return null;
}

function CheckLine({ check }: { check: ThemeCheck | null }) {
  if (check === null) {
    return null;
  }
  if (check.passed) {
    return (
      <Text size="xs" c="green">
        Passed the checks.
      </Text>
    );
  }
  return (
    <Text size="xs" c="orange">
      Did not pass: {check.problems.join(" ")}
    </Text>
  );
}

function CandidateCard({
  candidate,
  busy,
  onChoose,
}: {
  candidate: ThemeCandidate;
  busy: boolean;
  onChoose: () => void;
}) {
  const { run } = candidate;
  return (
    <Paper
      withBorder
      p="sm"
      radius="md"
      style={candidate.chosen ? { borderColor: "var(--mantine-color-blue-6)" } : undefined}
    >
      <Stack gap="xs">
        <Group justify="space-between">
          <Text size="sm" fw={600}>
            Candidate {candidate.position}
          </Text>
          {candidate.chosen && <Badge variant="light">Canonical</Badge>}
        </Group>
        <Recording run={run} />
        {run !== null && <Measurements run={run} />}
        <CheckLine check={candidate.check} />
        {!candidate.chosen && run?.url != null && (
          <Group>
            <Button variant="default" size="xs" disabled={busy} onClick={onChoose}>
              Choose this one
            </Button>
          </Group>
        )}
      </Stack>
    </Paper>
  );
}

function VersionCard({
  version,
  busy,
  onRegenerate,
}: {
  version: ThemeVersion;
  busy: boolean;
  onRegenerate: () => void;
}) {
  const { run } = version;
  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Group justify="space-between">
          <Text size="sm" fw={600}>
            {version.emotion}
          </Text>
          {!version.current && (
            <Badge color="yellow" variant="light">
              Made from an earlier choice
            </Badge>
          )}
        </Group>
        <Recording run={run} />
        {run !== null && <Measurements run={run} />}
        <CheckLine check={version.check} />
        {version.current && (
          <Group>
            <Button variant="default" size="xs" disabled={busy} onClick={onRegenerate}>
              Make this again
            </Button>
          </Group>
        )}
      </Stack>
    </Paper>
  );
}
