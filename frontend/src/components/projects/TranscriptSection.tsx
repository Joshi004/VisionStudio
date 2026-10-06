import { Fragment, type CSSProperties } from "react";
import {
  Alert,
  Button,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import type { ProjectDetail } from "../../api/projects";
import { useStartTranscription, useTranscription, type Transcript } from "../../api/transcription";
import { formatDateTime } from "../../format";
import { JobActions } from "../jobs/JobActions";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { groupByParagraph, percent, staleMessage, wordTitle } from "./transcriptView";

// Words the recogniser did not hear: their times are estimated, so they look different.
const NOT_HEARD_STYLE: CSSProperties = {
  textDecoration: "underline dotted",
  textDecorationColor: "var(--mantine-color-orange-6)",
  color: "var(--mantine-color-orange-8)",
};

function CountsLine({ transcript }: { transcript: Transcript }) {
  const { counts } = transcript;
  return (
    <Text size="sm" c="dimmed">
      {counts.matched} of {counts.script_words} script words matched (
      {percent(counts.matched, counts.script_words)}) · {counts.interpolated} not heard, times
      estimated · {counts.extra_spoken} extra spoken words ignored · transcribed{" "}
      {formatDateTime(transcript.created_at)}
      {transcript.processing_time !== null && ` · ${Math.round(transcript.processing_time)} s on the server`}
    </Text>
  );
}

function ScriptWords({ transcript }: { transcript: Transcript }) {
  const paragraphs = groupByParagraph(transcript.script_words);
  return (
    <Stack gap="xs">
      <ScrollArea.Autosize mah={420} type="auto">
        <Stack gap="sm" pr="sm">
          {paragraphs.map((words) => (
            <Text key={words[0].index} component="p" m={0} lh={1.7}>
              {words.map((word) => (
                <Fragment key={word.index}>
                  <span title={wordTitle(word)} style={word.matched ? undefined : NOT_HEARD_STYLE}>
                    {word.word}
                  </span>{" "}
                </Fragment>
              ))}
            </Text>
          ))}
        </Stack>
      </ScrollArea.Autosize>
      <Text size="xs" c="dimmed">
        <span style={NOT_HEARD_STYLE}>Dotted orange</span> words were not heard in the recording,
        so their times are estimated. Rest the pointer on a word to see its time.
      </Text>
    </Stack>
  );
}

export function TranscriptSection({ project }: { project: ProjectDetail }) {
  const { data, isLoading, isError, error, dataUpdatedAt } = useTranscription(project.id);
  const start = useStartTranscription(project.id);
  // Elapsed times are worked out from the stored times as of the last time the data was
  // loaded (on page load, Refresh or returning to the tab). There is no timer.
  const now = dataUpdatedAt;

  const job = data?.job ?? null;
  const transcript = data?.transcript ?? null;
  const isActive = job !== null && (job.status === "queued" || job.status === "running");
  const hasScript = project.script_text !== null && project.script_text.trim() !== "";

  let blockedReason: string | null = null;
  if (!project.voiceover) {
    blockedReason = "Upload a voiceover first.";
  } else if (!hasScript) {
    blockedReason = "Paste the script first.";
  } else if (isActive) {
    blockedReason = "A transcription is already in progress.";
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Title order={4}>Transcript</Title>
          <Group gap="sm">
            {blockedReason && (
              <Text size="xs" c="dimmed">
                {blockedReason}
              </Text>
            )}
            <Button
              onClick={() => start.mutate()}
              disabled={blockedReason !== null}
              loading={start.isPending}
            >
              {transcript ? "Transcribe again" : "Transcribe"}
            </Button>
          </Group>
        </Group>

        {isLoading && <Loader size="sm" />}

        {isError && (
          <Alert color="red" title="Could not load the transcript">
            {describeError(error)} Press Refresh to try again.
          </Alert>
        )}

        {start.isError && (
          <Alert color="red" title="The transcription was not started">
            {describeError(start.error)}
          </Alert>
        )}

        {job && (
          <Stack gap={4}>
            <Group gap="sm">
              <JobStatusBadge job={job} />
              <Text size="sm" c="dimmed">
                {elapsedText(job, now)}
              </Text>
              <JobActions job={job} />
            </Group>
            {isActive && (
              <Text size="xs" c="dimmed">
                A transcription takes about 2 minutes. Press Refresh to see its progress.
              </Text>
            )}
          </Stack>
        )}

        {job?.status === "failed" && job.error && (
          <Alert color="red" title="The transcription failed">
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {job.error}
            </Text>
          </Alert>
        )}

        {data && !job && !transcript && <Text c="dimmed">No transcript yet.</Text>}

        {transcript && transcript.stale_reasons.length > 0 && (
          <Alert color="yellow" title="This transcript is out of date">
            {transcript.stale_reasons.map((reason) => (
              <Text key={reason} size="sm">
                {staleMessage(reason)}
              </Text>
            ))}
            <Text size="sm">Transcribe again to update it.</Text>
          </Alert>
        )}

        {transcript && transcript.warnings.length > 0 && (
          <Alert color="orange" title="The recording differs from the script">
            {transcript.warnings.map((warning) => (
              <Text key={warning} size="sm">
                {warning}
              </Text>
            ))}
            <Text size="sm">You can fix the script or go on with the times as they are.</Text>
          </Alert>
        )}

        {transcript && (
          <>
            <CountsLine transcript={transcript} />
            <ScriptWords transcript={transcript} />
          </>
        )}
      </Stack>
    </Paper>
  );
}
