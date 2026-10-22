import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useChooseNarratorVoice,
  useDeriveNarratorVoice,
  useNarratorVoice,
  type NarratorVoice,
} from "../../api/storyVoices";
import { useVoices } from "../../api/voiceLab";
import { PromptHoverCard } from "./PromptHoverCard";

type NarratorVoicePanelProps = {
  projectId: number;
};

const STATUS: Record<NarratorVoice["status"], { label: string; color: string }> = {
  unavailable: { label: "Not available", color: "gray" },
  none: { label: "No voice", color: "gray" },
  in_progress: { label: "Making", color: "blue" },
  failed: { label: "Failed", color: "red" },
  ready: { label: "Ready", color: "green" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

function progressText(narrator: NarratorVoice): string | null {
  if (narrator.status !== "in_progress") {
    return null;
  }
  return narrator.stage === "making_sample"
    ? "Making the voice sample."
    : "Writing the voice description.";
}

function deriveLabel(narrator: NarratorVoice): string {
  if (narrator.status === "failed") {
    return "Retry";
  }
  return narrator.version === null ? "Derive from the Story Bible" : "Derive again";
}

/**
 * The narrator half of the Voices stage: the project's narrator voice. It is derived from the
 * Story Bible's storytelling style, the same way as a character's voice, or chosen by hand from
 * the saved voices. Deriving a voice over one chosen by hand asks first.
 */
export function NarratorVoicePanel({ projectId }: NarratorVoicePanelProps) {
  const { data: narrator, isLoading, isError, error } = useNarratorVoice(projectId);
  const voices = useVoices();
  const derive = useDeriveNarratorVoice(projectId);
  const choose = useChooseNarratorVoice(projectId);
  const [confirming, setConfirming] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);

  const busy = derive.isPending || choose.isPending;
  const status = narrator ? STATUS[narrator.status] : null;
  const progress = narrator ? progressText(narrator) : null;
  const active = narrator?.status === "in_progress";
  const source = narrator?.version?.source ?? null;

  const options = (voices.data ?? []).map((voice) => ({
    value: String(voice.id),
    label: voice.name,
  }));

  const startDerive = () => {
    if (narrator?.needs_confirmation) {
      setConfirming(true);
    } else {
      derive.mutate({ confirmReplaceManual: false });
    }
  };

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>Narrator voice</Title>
            <Text size="sm" c="dimmed">
              The voice that reads the narration. It is made from the Story Bible&apos;s
              storytelling style, or you can choose a saved voice.
            </Text>
          </Stack>
          {narrator && (
            <Button
              variant="default"
              loading={active}
              disabled={!narrator.can_run || busy}
              onClick={startDerive}
            >
              {deriveLabel(narrator)}
            </Button>
          )}
        </Group>

        {isLoading && <Loader size="sm" />}
        {isError && (
          <Alert color="red" title="Could not load the narrator voice">
            {describeError(error)}
          </Alert>
        )}
        {derive.isError && (
          <Alert color="red" title="Could not start the narrator voice">
            {describeError(derive.error)}
          </Alert>
        )}
        {choose.isError && (
          <Alert color="red" title="Could not set the narrator voice">
            {describeError(choose.error)}
          </Alert>
        )}

        {narrator && status && (
          <Stack gap={4}>
            <Group gap="xs">
              <Badge variant="light" color={status.color}>
                {status.label}
              </Badge>
              {source !== null && (
                <Badge variant="light" color={source === "ai" ? "blue" : "teal"}>
                  {source === "ai" ? "from the Story Bible" : "chosen by hand"}
                </Badge>
              )}
              {narrator.version !== null && (
                <PromptHoverCard
                  jobId={narrator.version.job_id}
                  source={narrator.version.source}
                  codeNote="A saved voice chosen for this project. No model was asked."
                >
                  <Badge variant="light" style={{ cursor: "help" }}>
                    v{narrator.version.version}
                  </Badge>
                </PromptHoverCard>
              )}
              {narrator.voice !== null && (
                <Text size="sm" fw={500}>
                  {narrator.voice.name}
                </Text>
              )}
            </Group>
            {progress !== null && (
              <Group gap="xs">
                <Loader size="xs" />
                <Text size="xs" c="dimmed">
                  {progress}
                </Text>
              </Group>
            )}
            {narrator.blocked_reason !== null && !active && (
              <Text size="xs" c="dimmed">
                {narrator.blocked_reason}
              </Text>
            )}
            {narrator.reasons.map((text) => (
              <Text key={text} size="xs" c="yellow.8">
                {text}
              </Text>
            ))}
            {narrator.status === "failed" && narrator.error !== null && (
              <Alert color="red" p="xs" title="The narrator voice could not be made">
                {narrator.error}
              </Alert>
            )}
            {narrator.instruction !== null && (
              <Text size="xs" c="dimmed">
                Designed from: {narrator.instruction}
              </Text>
            )}
            {narrator.voice !== null && (
              <audio
                src={narrator.voice.url}
                controls
                preload="metadata"
                style={{ width: "100%" }}
              />
            )}
          </Stack>
        )}

        <Group align="flex-end" gap="sm">
          <Select
            label="Or choose a saved voice"
            placeholder={voices.isLoading ? "Loading voices" : "Choose a voice"}
            data={options}
            value={picked}
            onChange={setPicked}
            searchable
            nothingFoundMessage="No saved voices"
            disabled={busy}
            style={{ flexGrow: 1 }}
          />
          <Button
            variant="default"
            disabled={picked === null || busy}
            loading={choose.isPending}
            onClick={() => {
              if (picked !== null) {
                choose.mutate(Number(picked), { onSuccess: () => setPicked(null) });
              }
            }}
          >
            Use this voice
          </Button>
        </Group>
      </Stack>

      <Modal
        opened={confirming}
        onClose={() => setConfirming(false)}
        title="Replace the narrator's voice?"
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            The narrator&apos;s voice was chosen by hand. Deriving one from the Story Bible
            replaces that choice. The earlier voice stays in the saved voices.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button
              color="red"
              onClick={() => {
                derive.mutate({ confirmReplaceManual: true });
                setConfirming(false);
              }}
            >
              Derive a voice
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
}
