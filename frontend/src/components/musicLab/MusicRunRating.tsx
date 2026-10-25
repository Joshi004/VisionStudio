import { useState } from "react";
import { SegmentedControl, Stack, Text, TextInput, Group } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useRunMeasurements,
  useRunOutsideWindow,
  useUpdateMusicRun,
  type LabMusicRun,
  type MusicVerdict,
} from "../../api/musicLab";
import { measurementLine, outsideWindowLine } from "./musicEditView";

const VERDICTS: { value: MusicVerdict; label: string }[] = [
  { value: "good", label: "Good" },
  { value: "usable", label: "Usable" },
  { value: "bad", label: "Bad" },
];

/** What you decided after listening, and a note to yourself. Saved as soon as you choose. */
export function Verdict({ run }: { run: LabMusicRun }) {
  const update = useUpdateMusicRun();
  const [note, setNote] = useState(run.note ?? "");

  function saveNote() {
    const trimmed = note.trim();
    if (trimmed !== (run.note ?? "")) {
      update.mutate({ runId: run.id, body: { note: trimmed === "" ? null : trimmed } });
    }
  }

  return (
    <Stack gap={4}>
      <Group gap="xs" wrap="nowrap">
        <SegmentedControl
          size="xs"
          // Nothing is selected while there is no verdict: "none" matches no button.
          value={run.verdict ?? "none"}
          onChange={(value) => {
            // Pressing the chosen button again clears the verdict.
            const verdict = value === run.verdict ? null : (value as MusicVerdict);
            update.mutate({ runId: run.id, body: { verdict } });
          }}
          data={[{ value: "none", label: "?", disabled: true }, ...VERDICTS]}
        />
        <TextInput
          size="xs"
          placeholder="A note: what you heard"
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
          onBlur={saveNote}
          maxLength={1000}
          style={{ flex: 1 }}
        />
      </Group>
      {update.isError && (
        <Text size="xs" c="red">
          {describeError(update.error)}
        </Text>
      )}
    </Stack>
  );
}

/** What was measured in the sound (its length, its silences, its loudest moment, its ending). */
export function Measurements({ run }: { run: LabMusicRun }) {
  const measurement = useRunMeasurements(run.id, run.url !== null);
  if (run.url === null) {
    return null;
  }
  return (
    <Text size="xs" c="dimmed">
      {measurement.isLoading && "Measuring the sound…"}
      {measurement.isError && "The sound could not be measured."}
      {measurement.data && measurementLine(measurement.data)}
    </Text>
  );
}

/** For a repaint or an inpaint: whether the sound outside its window stayed the same. */
export function OutsideWindowLine({ run }: { run: LabMusicRun }) {
  const hasWindow = run.operation === "repaint" || run.operation === "inpaint";
  const comparison = useRunOutsideWindow(run.id, hasWindow && run.url !== null);
  if (!hasWindow || run.url === null) {
    return null;
  }
  return (
    <Text size="xs" c={comparison.data && !comparison.data.unchanged ? "orange" : "dimmed"}>
      {comparison.isLoading && "Comparing the sound outside the window with the source…"}
      {comparison.isError && "The sound outside the window could not be compared."}
      {comparison.data && outsideWindowLine(comparison.data)}
    </Text>
  );
}
