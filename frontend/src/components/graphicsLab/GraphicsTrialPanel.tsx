import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  SegmentedControl,
  Select,
  Stack,
  Text,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useGraphicsTrials,
  useStartGraphicsTrial,
  type GraphicTrialOrientation,
} from "../../api/graphicsLab";
import { useVoices } from "../../api/voiceLab";
import { ORIENTATION_LABELS } from "./graphicsLabView";
import { costText, ORIENTATION_MODE_LABELS } from "./graphicsTrialView";

type GraphicsTrialPanelProps = {
  /** Opens the summary of a trial set. */
  onOpenTrial: (setNo: number) => void;
};

/**
 * The trial batch (GFX-012): the ten excerpts of Appendix A through every engine. The form picks
 * a voice (or none) and an orientation. **Run the trial** is a paid action, so it first shows
 * what it will do (the paid calls, and the speeches with a voice) and starts only when that is
 * confirmed. The sets made so far are listed with a link to each one's summary.
 */
export function GraphicsTrialPanel({ onOpenTrial }: GraphicsTrialPanelProps) {
  const trials = useGraphicsTrials();
  const start = useStartGraphicsTrial();
  const voices = useVoices().data ?? [];
  const [voiceId, setVoiceId] = useState<string | null>(null);
  const [orientation, setOrientation] = useState<GraphicTrialOrientation>("own");
  const [confirming, setConfirming] = useState(false);

  const data = trials.data;
  const cost = data ? (voiceId === null ? data.cost : data.cost_with_voice) : null;

  function close() {
    setConfirming(false);
    start.reset();
  }

  function begin() {
    start.mutate(
      { voice_id: voiceId === null ? null : Number(voiceId), orientation },
      {
        onSuccess: (started) => {
          close();
          onOpenTrial(started.set_no);
        },
      },
    );
  }

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Runs the ten excerpts of Appendix A through the building blocks and the generated
        component, one run each, and counts the results. It is a paid action: it asks the model
        for ten briefs and for what each engine needs, and it starts only after you confirm the
        number of calls. The runs are ordinary runs: open, judge or delete them like any other.
        The template engines are no longer made; older trial sets keep their template results.
      </Text>

      {trials.isLoading && <Loader size="sm" />}
      {trials.isError && (
        <Alert color="red" title="Could not load the trial">
          {describeError(trials.error)}
        </Alert>
      )}

      {data && (
        <>
          <details>
            <summary style={{ cursor: "pointer", fontSize: "var(--mantine-font-size-sm)" }}>
              The {data.excerpts.length} excerpts
            </summary>
            <Stack gap="xs" mt="xs">
              {data.excerpts.map((excerpt) => (
                <Stack key={excerpt.key} gap={2}>
                  <Group gap="xs">
                    <Badge variant="outline">{excerpt.key}</Badge>
                    <Text size="xs" c="dimmed">
                      {excerpt.domain} · {ORIENTATION_LABELS[excerpt.orientation]} ·{" "}
                      {excerpt.tests}
                    </Text>
                  </Group>
                  <Text size="sm" style={{ wordBreak: "break-word" }}>
                    {excerpt.text}
                  </Text>
                </Stack>
              ))}
            </Stack>
          </details>

          <Select
            label="Voice (optional)"
            description="A saved voice reads every excerpt (ten speeches on the remote server). Without a voice, the times are estimated."
            placeholder={voices.length === 0 ? "No saved voices yet" : "No voice"}
            data={voices.map((voice) => ({ value: String(voice.id), label: voice.name }))}
            value={voiceId}
            onChange={setVoiceId}
            clearable
            searchable
            nothingFoundMessage="No such voice"
          />

          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Orientation
            </Text>
            <SegmentedControl
              value={orientation}
              onChange={(value) => setOrientation(value as GraphicTrialOrientation)}
              data={(Object.keys(ORIENTATION_MODE_LABELS) as GraphicTrialOrientation[]).map(
                (value) => ({ value, label: ORIENTATION_MODE_LABELS[value] }),
              )}
            />
          </Stack>

          {cost && (
            <Text size="sm" fw={600}>
              This will make {costText(cost)}.
            </Text>
          )}

          <Group>
            <Button onClick={() => setConfirming(true)} disabled={cost === null}>
              Run the trial
            </Button>
          </Group>

          <Stack gap="xs">
            <Text size="sm" fw={600}>
              Trial sets
            </Text>
            {data.sets.length === 0 && (
              <Text size="sm" c="dimmed">
                No trial yet. Each trial makes a new set, and the summary can be switched between
                sets.
              </Text>
            )}
            {data.sets.map((item) => (
              <Group key={item.set_no} justify="space-between">
                <Text size="sm">
                  Set {item.set_no}{" "}
                  <Text span size="xs" c="dimmed">
                    · {item.runs} runs · {new Date(item.created_at).toLocaleString()}
                  </Text>
                </Text>
                <Button size="compact-xs" variant="subtle" onClick={() => onOpenTrial(item.set_no)}>
                  Open summary
                </Button>
              </Group>
            ))}
          </Stack>
        </>
      )}

      <Modal opened={confirming} onClose={close} title="Run the trial?" centered>
        <Stack gap="md">
          {cost && (
            <Text size="sm">
              This starts {costText(cost)}. The model calls are paid, and so are the retries.
              Deleting the runs afterwards does not give the cost back.
            </Text>
          )}
          {start.isError && (
            <Alert color="red" title="The trial was not started">
              {describeError(start.error)}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={close} disabled={start.isPending}>
              Cancel
            </Button>
            <Button onClick={begin} loading={start.isPending}>
              Start the trial
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
