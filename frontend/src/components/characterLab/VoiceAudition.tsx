import { useState } from "react";
import { Alert, Badge, Button, Group, Loader, Paper, Select, SimpleGrid, Stack, Text, TextInput, Textarea } from "@mantine/core";

import {
  useSetVoice,
  useSetVoiceDescription,
  useStartAuditionLine,
  useStartAuditions,
  type AuditionSample,
  type LibraryCharacter,
} from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { useJob } from "../../api/jobs";
import { useVoiceLabRun, useVoices } from "../../api/voiceLab";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { LicenseNotice } from "../voiceLab/LicenseNotice";
import { auditionProblem, LIMITS, normalizedText, voiceNameProblem } from "./characterLabView";

/** The line a finished "write a line" job wrote, or null while it has none. */
function auditionLineOf(output: unknown): string | null {
  if (typeof output === "object" && output !== null && "audition_line" in output) {
    const line = output.audition_line;
    return typeof line === "string" && line.trim() !== "" ? line : null;
  }
  return null;
}

function SampleCard({
  sample,
  position,
  nameProblem,
  choosing,
  onChoose,
}: {
  sample: AuditionSample;
  position: number;
  nameProblem: string | null;
  choosing: boolean;
  onChoose: () => void;
}) {
  const run = useVoiceLabRun(sample.voice_run_id);
  const job = run.data?.job ?? sample.job;
  const url = run.data?.url ?? sample.url;
  const failed = job !== null && (job.status === "failed" || job.status === "cancelled");
  return (
    <Paper withBorder p="xs" radius="md">
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap">
          <Text size="sm" fw={500}>
            Sample {position}
          </Text>
          {job !== null && <JobStatusBadge job={job} />}
        </Group>
        {url !== null ? (
          <audio src={url} controls preload="metadata" style={{ width: "100%" }} />
        ) : failed ? (
          <Text size="xs" c="red">
            {job?.error ?? "This sample could not be made."}
          </Text>
        ) : (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="xs" c="dimmed">
              One to three minutes.
            </Text>
          </Group>
        )}
        <Button
          size="compact-sm"
          disabled={url === null || nameProblem !== null}
          loading={choosing}
          onClick={onChoose}
        >
          Use this voice
        </Button>
      </Stack>
    </Paper>
  );
}

/**
 * The voice step, all optional: a character without a voice is mute (pictures and silent clips
 * only). Give it a voice by choosing one already saved, or by auditioning: describe the voice,
 * read one line three ways, and keep the sample you like as a named voice.
 */
export function VoiceAudition({ character }: { character: LibraryCharacter }) {
  const voices = useVoices();
  const setVoice = useSetVoice();
  const saveDescription = useSetVoiceDescription();
  const writeLine = useStartAuditionLine();
  const auditions = useStartAuditions();

  const [existingId, setExistingId] = useState<string | null>(
    character.voice ? String(character.voice.id) : null,
  );
  const [description, setDescription] = useState(character.voice_description ?? "");
  // The line is what was typed, or else what the language model wrote. A new "write a line"
  // click clears what was typed, so its answer is shown.
  const [typedLine, setTypedLine] = useState<string | null>(null);
  const [lineJobId, setLineJobId] = useState<number | null>(null);
  const [samples, setSamples] = useState<AuditionSample[]>([]);
  const [voiceName, setVoiceName] = useState(character.name);

  const lineJob = useJob(lineJobId);
  const writtenLine = lineJob.data?.status === "succeeded" ? auditionLineOf(lineJob.data.output) : null;
  const line = typedLine ?? writtenLine ?? "";
  const writingLine = writeLine.isPending || lineJob.data?.status === "queued" || lineJob.data?.status === "running";
  const lineFailed = lineJob.data?.status === "failed" || lineJob.data?.status === "cancelled";

  const problem = auditionProblem(description, line);
  const nameProblem = voiceNameProblem(voiceName);
  const descriptionChanged = normalizedText(description) !== normalizedText(character.voice_description ?? "");
  const failure = [setVoice, saveDescription, writeLine, auditions].find((mutation) => mutation.isError)?.error;

  function audition() {
    const start = () =>
      auditions.mutate({ characterId: character.id, line: line.trim() }, { onSuccess: setSamples });
    if (descriptionChanged) {
      // The samples are made from the saved description, so save it first.
      saveDescription.mutate(
        { characterId: character.id, voiceDescription: description.trim() },
        { onSuccess: start },
      );
    } else {
      start();
    }
  }

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Group gap="xs">
          <Text size="sm" fw={500}>
            Voice:
          </Text>
          {character.voice !== null ? (
            <Badge variant="light" color="grape">
              {character.voice.name}
            </Badge>
          ) : (
            <Badge variant="light" color="gray">
              Mute
            </Badge>
          )}
          {character.voice !== null && (
            <Button
              size="compact-xs"
              variant="default"
              loading={setVoice.isPending && setVoice.variables?.choice.source === "none"}
              onClick={() => setVoice.mutate({ characterId: character.id, choice: { source: "none" } })}
            >
              Make it mute
            </Button>
          )}
        </Group>
        <Text size="xs" c="dimmed">
          A mute character has no dialogue: you can make pictures and silent clips with it. You can
          give it a voice later.
        </Text>
      </Stack>

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Text fw={600}>Use a saved voice</Text>
          <Select
            label="Saved voice"
            placeholder={voices.data?.length === 0 ? "No saved voices yet" : "Choose a voice"}
            data={(voices.data ?? []).map((voice) => ({ value: String(voice.id), label: voice.name }))}
            value={existingId}
            onChange={setExistingId}
            searchable
            nothingFoundMessage="No such voice"
          />
          <Group>
            <Button
              disabled={existingId === null}
              loading={setVoice.isPending && setVoice.variables?.choice.source === "existing"}
              onClick={() =>
                existingId !== null &&
                setVoice.mutate({
                  characterId: character.id,
                  choice: { source: "existing", voice_id: Number(existingId) },
                })
              }
            >
              Use this voice
            </Button>
          </Group>
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Text fw={600}>Audition a new voice</Text>
          <Textarea
            label="Voice description"
            description={`For example: a warm, thoughtful young woman with a calm delivery. ${description.length} of ${LIMITS.voiceDescription} characters.`}
            value={description}
            onChange={(event) => setDescription(event.currentTarget.value)}
            autosize
            minRows={2}
          />
          <Textarea
            label="Sample line"
            description={`What the three samples say. ${line.length} of ${LIMITS.speech} characters.`}
            value={line}
            onChange={(event) => setTypedLine(event.currentTarget.value)}
            autosize
            minRows={2}
          />
          <Group gap="xs">
            <Button
              variant="default"
              size="compact-sm"
              loading={writingLine}
              onClick={() => {
                setTypedLine(null);
                writeLine.mutate(character.id, { onSuccess: (job) => setLineJobId(job.id) });
              }}
            >
              Write a line for me
            </Button>
            <Text size="xs" c="dimmed">
              One call to the language model, from the character's personality.
            </Text>
          </Group>
          {lineFailed && (
            <Alert color="red" p="xs" title="The line could not be written">
              {lineJob.data?.error ?? "No reason was given."}
            </Alert>
          )}

          <Stack gap={6} align="flex-start">
            <Button
              loading={auditions.isPending || saveDescription.isPending}
              disabled={problem !== null}
              onClick={audition}
            >
              Audition: make 3 samples
            </Button>
            {problem !== null && description.trim() !== "" && line.trim() !== "" && (
              <Alert color="yellow" p="xs">
                {problem}
              </Alert>
            )}
            <Text size="xs" c="dimmed">
              Three GPU jobs of one to three minutes. They start only when you press the button, and
              they also appear in the Voice tab.
            </Text>
            <LicenseNotice />
          </Stack>

          {samples.length > 0 && (
            <Stack gap="sm">
              <TextInput
                label="Name to save the chosen voice under"
                value={voiceName}
                onChange={(event) => setVoiceName(event.currentTarget.value)}
                error={nameProblem}
                maw={360}
              />
              <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
                {samples.map((sample, index) => (
                  <SampleCard
                    key={sample.voice_run_id}
                    sample={sample}
                    position={index + 1}
                    nameProblem={nameProblem}
                    choosing={
                      setVoice.isPending && setVoice.variables?.choice.voice_run_id === sample.voice_run_id
                    }
                    onChoose={() =>
                      setVoice.mutate(
                        {
                          characterId: character.id,
                          choice: {
                            source: "audition",
                            voice_run_id: sample.voice_run_id,
                            name: voiceName.trim(),
                          },
                        },
                        { onSuccess: () => setSamples([]) },
                      )
                    }
                  />
                ))}
              </SimpleGrid>
            </Stack>
          )}
        </Stack>
      </Paper>

      {failure != null && (
        <Alert color="red" p="xs">
          {describeError(failure)}
        </Alert>
      )}
    </Stack>
  );
}
