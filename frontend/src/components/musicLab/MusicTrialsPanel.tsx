import { useState } from "react";
import {
  Alert,
  Badge,
  Group,
  List,
  Loader,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  Textarea,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useMusicCatalog,
  useMusicTrials,
  useUpdateMusicTrial,
  type LabMusicRun,
  type MusicCatalog,
  type MusicTrialCase,
  type MusicTrialSource,
  type TrialAnswer,
} from "../../api/musicLab";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { Measurements, OutsideWindowLine, Verdict } from "./MusicRunRating";
import { secondsText } from "./musicEditView";
import { sentLines } from "./musicLabView";
import {
  ANSWER_LABELS,
  caseStatus,
  progressLine,
  runLabel,
  STATUS_COLORS,
  STATUS_LABELS,
  TRIAL_GROUPS,
} from "./musicTrialsView";

const ANSWERS: TrialAnswer[] = ["yes", "partly", "no"];

/** A recording to play, with its name and, for a join, where the two pieces meet. */
function SourcePlayer({ source }: { source: MusicTrialSource }) {
  return (
    <Stack gap={2}>
      <Text size="sm" fw={500}>
        {source.label}
        {source.duration_s !== null && (
          <Text span size="xs" c="dimmed">
            {" "}
            ({secondsText(source.duration_s)})
          </Text>
        )}
      </Text>
      {source.seam_s !== null && (
        <Text size="xs" c="dimmed">
          The two pieces meet at {secondsText(source.seam_s)}.
        </Text>
      )}
      {source.url !== null ? (
        <audio controls preload="none" src={source.url} style={{ width: "100%" }} />
      ) : (
        <Text size="xs" c="dimmed">
          The recording is not available yet.
        </Text>
      )}
    </Stack>
  );
}

/** One result: what it is, the sound, what was measured, and your rating. */
function OutputCard({
  run,
  label,
  catalog,
}: {
  run: LabMusicRun;
  label: string;
  catalog: MusicCatalog | undefined;
}) {
  const failed = run.job?.status === "failed";
  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Stack gap={0}>
            <Text size="sm" fw={600}>
              {label}
            </Text>
            <Text size="xs" c="dimmed">
              {run.model_label} · run {run.id}
            </Text>
          </Stack>
          {run.job && run.url === null && <JobStatusBadge job={run.job} />}
        </Group>

        {run.url !== null ? (
          <audio controls preload="none" src={run.url} style={{ width: "100%" }} />
        ) : failed ? (
          <Alert color="red" title="The run failed" p="xs">
            <Text size="xs" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {run.job?.error}
            </Text>
          </Alert>
        ) : (
          <Text size="xs" c="dimmed">
            Waiting for the sound. This page updates by itself.
          </Text>
        )}

        <Measurements run={run} />
        <OutsideWindowLine run={run} />

        <details>
          <summary style={{ cursor: "pointer", fontSize: "var(--mantine-font-size-xs)" }}>
            What was sent
          </summary>
          <Stack gap={2} mt={4}>
            {sentLines(run, catalog).map((line) => (
              <Text key={line} size="xs" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {line}
              </Text>
            ))}
          </Stack>
        </details>

        {run.url !== null && <Verdict run={run} />}
      </Stack>
    </Paper>
  );
}

/** Your answer to the case's question, and a note. Saved as soon as you choose. */
function AnswerBox({ trial }: { trial: MusicTrialCase }) {
  const update = useUpdateMusicTrial();
  const [note, setNote] = useState(trial.answer_note ?? "");

  function saveNote() {
    const trimmed = note.trim();
    if (trimmed !== (trial.answer_note ?? "")) {
      update.mutate({ caseId: trial.id, body: { answer_note: trimmed === "" ? null : trimmed } });
    }
  }

  return (
    <Stack gap="xs">
      <Text size="sm" fw={600}>
        Your answer: {trial.guide.question}
      </Text>
      <SegmentedControl
        size="xs"
        w={260}
        // Nothing is selected while there is no answer: "none" matches no button.
        value={trial.answer ?? "none"}
        onChange={(value) => {
          // Pressing the chosen button again clears the answer.
          const answer = value === trial.answer ? null : (value as TrialAnswer);
          update.mutate({ caseId: trial.id, body: { answer } });
        }}
        data={[
          { value: "none", label: "?", disabled: true },
          ...ANSWERS.map((answer) => ({ value: answer, label: ANSWER_LABELS[answer] })),
        ]}
      />
      <Textarea
        size="xs"
        autosize
        minRows={2}
        maxRows={8}
        placeholder="Your note for this case: what you decided and why (the run numbers help)"
        value={note}
        onChange={(event) => setNote(event.currentTarget.value)}
        onBlur={saveNote}
        maxLength={2000}
      />
      {update.isError && (
        <Text size="xs" c="red">
          {describeError(update.error)}
        </Text>
      )}
    </Stack>
  );
}

function CaseCard({ trial, catalog }: { trial: MusicTrialCase; catalog: MusicCatalog | undefined }) {
  const status = caseStatus(trial);
  const guide = trial.guide;
  const hasOutputs = trial.runs.length > 0 || trial.local_outputs.length > 0;
  return (
    <Paper withBorder p="md" radius="md" id={`trial-${trial.id}`}>
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Group gap="xs">
            <Badge variant="outline">{trial.id}</Badge>
            <Text fw={600}>{trial.title}</Text>
          </Group>
          <Badge color={STATUS_COLORS[status]} variant="light">
            {STATUS_LABELS[status]}
          </Badge>
        </Group>

        <Stack gap={4}>
          <Text size="sm" fw={600}>
            What to verify
          </Text>
          <List type="ordered" size="sm" spacing={4}>
            {guide.verify.map((line) => (
              <List.Item key={line}>{line}</List.Item>
            ))}
          </List>
        </Stack>

        {trial.sources.length > 0 && (
          <Stack gap="xs">
            <Text size="sm" fw={600}>
              Source audio (what we started from)
            </Text>
            <SimpleGrid cols={{ base: 1, md: 2 }}>
              {trial.sources.map((source) => (
                <SourcePlayer key={`${source.run_id ?? "s"}-${source.source_id ?? "r"}`} source={source} />
              ))}
            </SimpleGrid>
          </Stack>
        )}

        <Stack gap={4}>
          <Text size="sm" fw={600}>
            What we did
          </Text>
          <Text size="sm">{guide.did}</Text>
          <Text size="sm" fw={600} mt={4}>
            The prompt, in simple words
          </Text>
          <Text size="sm">{guide.prompt_plain}</Text>
        </Stack>

        <Stack gap="xs">
          <Text size="sm" fw={600}>
            What came out
          </Text>
          {!hasOutputs && (
            <Text size="sm" c="dimmed">
              Nothing has been made for this case yet. The runs appear here when they start.
            </Text>
          )}
          {trial.local_outputs.length > 0 && (
            <SimpleGrid cols={{ base: 1, md: 2 }}>
              {trial.local_outputs.map((source) => (
                <Paper key={source.source_id ?? source.label} withBorder p="sm" radius="md">
                  <SourcePlayer source={source} />
                </Paper>
              ))}
            </SimpleGrid>
          )}
          {trial.runs.length > 0 && (
            <SimpleGrid cols={{ base: 1, md: 2 }}>
              {trial.runs.map((run) => (
                <OutputCard key={run.id} run={run} label={runLabel(trial, run.id)} catalog={catalog} />
              ))}
            </SimpleGrid>
          )}
        </Stack>

        <AnswerBox trial={trial} />
      </Stack>
    </Paper>
  );
}

/**
 * Round 2 of the music trials: one card for each case, with what to verify, the audio it started
 * from, what was done, what came out (each result rated Good, Usable or Bad) and your answer.
 * Nothing here starts a GPU job: the runs are started by the trial helper, and they stay.
 */
export function MusicTrialsPanel() {
  const trials = useMusicTrials();
  const catalog = useMusicCatalog();
  const [group, setGroup] = useState<string>(TRIAL_GROUPS[0].id);
  const all = trials.data ?? [];

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        Each card is one question about the models. Read what to verify, play the source audio, then
        play what came out and rate each result Good, Usable or Bad. Finish a card with your answer
        to its question, and a note: those answers decide how the music pipeline is built. Nothing
        on this screen starts a paid run.
      </Text>

      {trials.isLoading && <Loader size="sm" />}
      {trials.isError && (
        <Alert color="red" title="Could not load the trial cases">
          {describeError(trials.error)} Press Refresh to try again.
        </Alert>
      )}
      {trials.data && all.length === 0 && (
        <Alert color="gray" title="No cases yet">
          The cases are written to the app by the trial helper (<code>music_lab_trials/round2.py sync</code>
          ).
        </Alert>
      )}

      {all.length > 0 && (
        <>
          <Text size="sm" fw={600}>
            {progressLine(all)}
          </Text>
          <Tabs keepMounted={false} value={group} onChange={(value) => value !== null && setGroup(value)}>
            <Tabs.List>
              {TRIAL_GROUPS.map((item) => {
                const cases = all.filter((trial) => trial.trial_group === item.id);
                const answered = cases.filter((trial) => trial.answer !== null).length;
                return (
                  <Tabs.Tab key={item.id} value={item.id}>
                    {item.label} ({answered}/{cases.length})
                  </Tabs.Tab>
                );
              })}
            </Tabs.List>
            {TRIAL_GROUPS.map((item) => (
              <Tabs.Panel key={item.id} value={item.id} pt="md">
                <Stack gap="md">
                  <Text size="sm" c="dimmed">
                    {item.about}
                  </Text>
                  {all
                    .filter((trial) => trial.trial_group === item.id)
                    .map((trial) => (
                      <CaseCard key={trial.id} trial={trial} catalog={catalog.data} />
                    ))}
                </Stack>
              </Tabs.Panel>
            ))}
          </Tabs>
        </>
      )}
    </Stack>
  );
}
