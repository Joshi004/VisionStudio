import { useRef, useState, type Dispatch, type SetStateAction } from "react";
import { Alert, Button, Group, Paper, SegmentedControl, Stack, Text, Textarea } from "@mantine/core";

import { useCreateAvTest } from "../../api/avLab";
import type { LibraryCharacter } from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { FirstFramePicker } from "../videoLab/FirstFramePicker";
import { AUDIO_MARKER_HINTS, ORIENTATION_LABELS } from "./characterLabView";
import {
  addPart,
  AV_INSTRUCTION_MAX_CHARS,
  AV_MARKER_LABELS,
  AV_MARKERS,
  AV_MAX_PARTS,
  AV_TEXT_MAX_CHARS,
  avFormProblem,
  partIndexOfWord,
  partOfSelection,
  partText,
  toAvTestIn,
  wordsOf,
  type AvFormState,
  type AvOrientation,
} from "./avLabView";
import { AvMarkedText } from "./AvMarkedText";
import type { AvMarker } from "../../api/avLab";

type AvTestFormProps = {
  character: LibraryCharacter;
  form: AvFormState;
  onChange: Dispatch<SetStateAction<AvFormState>>;
};

const ORIENTATIONS: AvOrientation[] = ["portrait", "landscape"];

/**
 * Makes a test: the text to speak whole, how to speak it, the parts of it to show as video, the
 * way a clip uses its part of the speech, and the picture every clip starts from.
 *
 * The parts are marked by selecting words in the text box and pressing "Mark as video". They
 * count words, so changing the text clears them.
 */
export function AvTestForm({ character, form, onChange }: AvTestFormProps) {
  const create = useCreateAvTest();
  const textBox = useRef<HTMLTextAreaElement>(null);
  const [markProblem, setMarkProblem] = useState<string | null>(null);
  const problem = avFormProblem(form, character);

  function update(changes: Partial<AvFormState>) {
    create.reset();
    onChange((current) => ({ ...current, ...changes }));
  }

  function changeText(text: string) {
    setMarkProblem(null);
    // A part is a range of word numbers, so another text means other words.
    update({ text, parts: [] });
  }

  function markSelection() {
    const box = textBox.current;
    if (box === null) {
      return;
    }
    const part = partOfSelection(form.text, box.selectionStart, box.selectionEnd);
    if (part === null) {
      setMarkProblem("Select some words of the text first.");
      return;
    }
    const added = addPart(form.parts, part);
    setMarkProblem(added.problem);
    if (added.problem === null) {
      update({ parts: added.parts });
    }
  }

  function removePart(number: number) {
    setMarkProblem(null);
    update({ parts: form.parts.filter((_, index) => index !== number) });
  }

  const wordCount = wordsOf(form.text).length;

  return (
    <Paper withBorder p="md" radius="md">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (problem === null && !create.isPending) {
            create.mutate({ characterId: character.id, body: toAvTestIn(form) });
          }
        }}
      >
        <Stack gap="md">
          <Text fw={600}>New test</Text>
          <Text size="sm" c="dimmed">
            The whole text is spoken as one take in this character&apos;s voice. The parts you mark
            also become video clips, made from that same speech. Then you can render the result two
            ways and compare them.
          </Text>

          <Textarea
            ref={textBox}
            label="Text"
            description={`${form.text.length} of ${AV_TEXT_MAX_CHARS} characters, ${wordCount} words.`}
            value={form.text}
            onChange={(event) => changeText(event.currentTarget.value)}
            autosize
            minRows={4}
            maxRows={14}
          />

          <Textarea
            label="How it is spoken"
            description={`Tone, emotion, pace. ${form.instruction.length} of ${AV_INSTRUCTION_MAX_CHARS} characters.`}
            value={form.instruction}
            onChange={(event) => update({ instruction: event.currentTarget.value })}
            autosize
            minRows={2}
          />

          <Stack gap="xs">
            <Group justify="space-between" align="center">
              <Text size="sm" fw={500}>
                Parts shown as video
              </Text>
              <Button
                size="compact-sm"
                variant="light"
                disabled={form.text.trim() === "" || form.parts.length >= AV_MAX_PARTS}
                onClick={markSelection}
              >
                Mark as video
              </Button>
            </Group>
            <Text size="xs" c="dimmed">
              Select words in the text box above, then press Mark as video. Each part becomes one
              paid H3 clip, up to {AV_MAX_PARTS} parts. A clip lasts at most 14 seconds, so keep a
              part to about 35 words or fewer.
            </Text>
            {markProblem !== null && (
              <Alert color="orange" p="xs">
                {markProblem}
              </Alert>
            )}
            {form.parts.length > 0 && (
              <>
                <AvMarkedText
                  text={form.text}
                  parts={form.parts}
                  onWordClick={(word) => {
                    const index = partIndexOfWord(form.parts, word);
                    if (index >= 0) {
                      removePart(index);
                    }
                  }}
                />
                <Stack gap={4}>
                  {form.parts.map((part, number) => (
                    <Group key={part.start_word} gap="xs" wrap="nowrap" justify="space-between">
                      <Text size="sm" lineClamp={2}>
                        <Text span fw={600}>
                          Part {number + 1}:{" "}
                        </Text>
                        {partText(form.text, part)}
                      </Text>
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        color="red"
                        onClick={() => removePart(number)}
                      >
                        Remove
                      </Button>
                    </Group>
                  ))}
                </Stack>
              </>
            )}
          </Stack>

          <Stack gap={4}>
            <Text size="sm" fw={500}>
              How a clip uses its part of the speech
            </Text>
            <SegmentedControl
              value={form.audioMarker}
              onChange={(value) => update({ audioMarker: value as AvMarker })}
              data={AV_MARKERS.map((marker) => ({ value: marker, label: AV_MARKER_LABELS[marker] }))}
            />
            <Text size="xs" c="dimmed">
              {AUDIO_MARKER_HINTS[form.audioMarker]}
            </Text>
          </Stack>

          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Shape
            </Text>
            <SegmentedControl
              value={form.orientation}
              onChange={(value) => update({ orientation: value as AvOrientation })}
              data={ORIENTATIONS.map((value) => ({ value, label: ORIENTATION_LABELS[value] }))}
            />
          </Stack>

          <FirstFramePicker
            value={form.firstFrame}
            onChange={(firstFrame) => update({ firstFrame })}
            title="First frame"
            emptyText="No picture chosen yet."
            hint="Every clip starts near this picture, and the video shows it between the parts."
          />

          <Group gap="sm" align="center">
            <Button type="submit" loading={create.isPending} disabled={problem !== null}>
              Make the test
            </Button>
            <Text size="xs" c="dimmed">
              {problem ??
                `Costs one speech and ${form.parts.length} video clip${form.parts.length === 1 ? "" : "s"}. The clips start by themselves once the speech is made and its words are timed.`}
            </Text>
          </Group>
          {create.isError && (
            <Alert color="red" p="xs" title="Nothing was started">
              {describeError(create.error)}
            </Alert>
          )}
        </Stack>
      </form>
    </Paper>
  );
}
