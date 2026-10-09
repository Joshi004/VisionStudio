import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  NumberInput,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";

import type { ProjectDetail, ProjectUpdate } from "../../api/projects";
import { capitalise } from "../../format";
import { INHERIT, modelChoices, videoModelLabel } from "../../videoModels";
import { changedFields, initialDraft, type Draft, type NUMBER_FIELDS } from "./settingsDraft";

type ProjectSettingsFormProps = {
  project: ProjectDetail;
  isSaving: boolean;
  isSaved: boolean;
  error: string | null;
  onEdit: () => void;
  onSave: (changes: ProjectUpdate) => void;
};

/**
 * The drafts live here. The page gives this component a `settingsKey`, so the
 * drafts start again from the saved values after every save.
 */
export function ProjectSettingsForm({
  project,
  isSaving,
  isSaved,
  error,
  onEdit,
  onSave,
}: ProjectSettingsFormProps) {
  const [draft, setDraft] = useState<Draft>(() => initialDraft(project));
  const changes = changedFields(project, draft);
  const unchanged = Object.keys(changes).length === 0;

  function edit<K extends keyof Draft>(field: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [field]: value }));
    onEdit();
  }

  function numberInput(
    field: (typeof NUMBER_FIELDS)[number],
    label: string,
    options: { step: number; min: number; max: number; decimalScale?: number; suffix?: string },
  ) {
    return (
      <NumberInput
        label={label}
        value={draft[field]}
        onChange={(value) => edit(field, value)}
        step={options.step}
        min={options.min}
        max={options.max}
        decimalScale={options.decimalScale ?? 0}
        allowNegative={false}
        clampBehavior="none"
        suffix={options.suffix}
        style={{ flex: 1 }}
      />
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!unchanged) {
          onSave(changes);
        }
      }}
    >
      <Stack gap="lg">
        <Paper withBorder p="md" radius="md">
          <Stack gap="md">
            <Title order={4}>Name</Title>
            <TextInput
              aria-label="Name"
              value={draft.name}
              onChange={(event) => edit("name", event.currentTarget.value)}
              maxLength={200}
            />
          </Stack>
        </Paper>

        <Paper withBorder p="md" radius="md">
          <Stack gap="md">
            <Group gap="sm">
              <Title order={4}>Video size</Title>
              <Badge variant="light">{capitalise(project.orientation)}</Badge>
              <Text size="xs" c="dimmed">
                The orientation is fixed after creation. Both sizes must keep its shape.
              </Text>
            </Group>

            <Stack gap={4}>
              <Group grow align="flex-start">
                {numberInput("gen_width", "Generation width", { step: 64, min: 256, max: 3840 })}
                {numberInput("gen_height", "Generation height", { step: 64, min: 256, max: 3840 })}
              </Group>
              <Text size="xs" c="dimmed">
                Sent to the video model. Multiples of 64 only. Create your frames at{" "}
                <Text span fw={600} inherit>
                  {String(draft.gen_width)} x {String(draft.gen_height)}
                </Text>
                .
              </Text>
            </Stack>

            <Stack gap={4}>
              <Group grow align="flex-start">
                {numberInput("out_width", "Output width", { step: 2, min: 256, max: 3840 })}
                {numberInput("out_height", "Output height", { step: 2, min: 256, max: 3840 })}
              </Group>
              <Text size="xs" c="dimmed">
                Size of the final video. Even numbers only (H.264 needs them).
              </Text>
            </Stack>

            <Group grow align="flex-start">
              {numberInput("fps", "Frames per second", { step: 1, min: 12, max: 60 })}
              <div />
            </Group>
          </Stack>
        </Paper>

        <Paper withBorder p="md" radius="md">
          <Stack gap="md">
            <Title order={4}>Scene length</Title>
            <Group grow align="flex-start">
              {numberInput("min_scene_seconds", "Minimum (seconds)", {
                step: 0.5,
                min: 0.5,
                max: 20,
                decimalScale: 2,
              })}
              {numberInput("max_scene_seconds", "Maximum (seconds)", {
                step: 0.5,
                min: 0.5,
                max: 20,
                decimalScale: 2,
              })}
            </Group>
            <Text size="xs" c="dimmed">
              The minimum must be below the maximum. A change applies to the next proposal and never
              re-cuts scenes that already exist.
            </Text>
          </Stack>
        </Paper>

        <Paper withBorder p="md" radius="md">
          <Stack gap="md">
            <Title order={4}>Video model</Title>
            <Select
              aria-label="Video model"
              description="Makes this project's clips unless a scene chooses its own (in its clip section). Regenerate can also pick a model for one take."
              data={modelChoices(
                `App default (currently ${videoModelLabel(project.default_video_model)})`,
              )}
              value={draft.video_model === "" ? INHERIT : draft.video_model}
              onChange={(value) =>
                edit("video_model", value === null || value === INHERIT ? "" : value)
              }
              allowDeselect={false}
              maw={360}
            />
            <Text size="xs" c="dimmed">
              LTX-2.5 has no negative prompt, so the Negative prompt below is used by LTX-2.3 only.
              A scene that has a last frame is always made by LTX-2.3 for now.
            </Text>
          </Stack>
        </Paper>

        <Paper withBorder p="md" radius="md">
          <Stack gap="md">
            <Title order={4}>Clip sound</Title>
            <NumberInput
              label="Volume"
              description="How loud each clip's own sound is, as a percent of the voiceover's level: 100 is as loud as the voice, 20 is about 14 dB under it, 5 about 26 dB under. Each clip is measured, so every scene sits at the same level. 0 turns it off."
              value={draft.clip_sound_percent}
              onChange={(value) => edit("clip_sound_percent", value)}
              step={5}
              min={0}
              max={100}
              decimalScale={0}
              allowNegative={false}
              clampBehavior="none"
              suffix=" %"
              maw={360}
            />
          </Stack>
        </Paper>

        <Paper withBorder p="md" radius="md">
          <Stack gap="md">
            <Title order={4}>Guidelines</Title>
            <Text size="xs" c="dimmed">
              Added to every scene so all of them share one look. Describe style, camera, lighting
              and pacing, not what the characters look like.
            </Text>
            <TextInput
              label="Style prefix"
              description='Sent as "Style: ..." at the start of every prompt, for example cinematic-realistic.'
              value={draft.style_prefix}
              onChange={(event) => edit("style_prefix", event.currentTarget.value)}
            />
            <Textarea
              label="Prompt suffix"
              description="Always added at the end, for example: static camera, soft warm light, muted palette."
              value={draft.prompt_suffix}
              onChange={(event) => edit("prompt_suffix", event.currentTarget.value)}
              autosize
              minRows={2}
            />
            <Textarea
              label="Negative prompt (LTX-2.3 only)"
              description="What to avoid, for example: blurry, low quality, text, watermark, speech, talking, voices. Leave blank to use the app's default (Settings, Video model). LTX-2.5 ignores it: say what you want in the prompt instead."
              value={draft.negative_prompt}
              onChange={(event) => edit("negative_prompt", event.currentTarget.value)}
              autosize
              minRows={2}
            />
          </Stack>
        </Paper>

        <Paper withBorder p="md" radius="md">
          <Stack gap="md">
            <Title order={4}>AI cut instructions</Title>
            <Textarea
              aria-label="AI cut instructions"
              description="Optional extra instructions for the AI that proposes where scenes are cut."
              value={draft.cut_instructions}
              onChange={(event) => edit("cut_instructions", event.currentTarget.value)}
              autosize
              minRows={2}
            />
          </Stack>
        </Paper>

        <Paper withBorder p="md" radius="md">
          <Stack gap="md">
            <Title order={4}>AI description instructions</Title>
            <Textarea
              aria-label="AI description instructions"
              description="Optional extra instructions for the AI that drafts the video prompts and first frame descriptions: places and recurring subjects to use (animals, objects, people where needed), the look, or sound wishes (it adds no music by default). They come before the AI's own rules wherever they differ."
              value={draft.description_instructions}
              onChange={(event) => edit("description_instructions", event.currentTarget.value)}
              autosize
              minRows={3}
            />
          </Stack>
        </Paper>

        <Group>
          <Button type="submit" disabled={unchanged} loading={isSaving}>
            Save settings
          </Button>
          {isSaved && unchanged && (
            <Text size="sm" c="green">
              Saved
            </Text>
          )}
        </Group>

        {error && !unchanged && (
          <Alert color="red" title="The settings were not saved">
            {error}
          </Alert>
        )}
      </Stack>
    </form>
  );
}
