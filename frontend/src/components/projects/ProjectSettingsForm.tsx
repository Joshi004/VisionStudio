import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  NumberInput,
  Paper,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from "@mantine/core";

import type { ProjectDetail, ProjectUpdate } from "../../api/projects";
import { capitalise } from "../../format";
import { projectKindLabel } from "./projectKinds";
import { speechModeLabel } from "./speechModes";
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
    options: { step: number; min: number; max: number },
  ) {
    return (
      <NumberInput
        label={label}
        value={draft[field]}
        onChange={(value) => edit(field, value)}
        step={options.step}
        min={options.min}
        max={options.max}
        decimalScale={0}
        allowNegative={false}
        clampBehavior="none"
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
          <Group gap="sm">
            <Title order={4}>Kind</Title>
            <Badge variant="light">{projectKindLabel(project.kind)}</Badge>
            <Text size="xs" c="dimmed">
              The kind is fixed after creation.
              {project.kind === "explainer" &&
                " The presenter and the set are chosen when the project is created."}
            </Text>
          </Group>
        </Paper>

        {project.kind === "story" && (
          <Paper withBorder p="md" radius="md">
            <Group gap="sm">
              <Title order={4}>Speech</Title>
              <Badge variant="light">{speechModeLabel(project.speech_mode)}</Badge>
              <Text size="xs" c="dimmed">
                The speech mode is fixed after creation.
              </Text>
            </Group>
          </Paper>
        )}

        <Paper withBorder p="md" radius="md">
          <Stack gap="xs">
            <Title order={4}>Music</Title>
            <Switch
              label="Plan and generate music for this story"
              checked={draft.music_enabled}
              onChange={(event) => edit("music_enabled", event.currentTarget.checked)}
            />
            <Text size="xs" c="dimmed">
              When off, the music steps are skipped and the video is made without music. It can be
              changed at any time.
            </Text>
            <Switch
              label="Include ambience in the video"
              checked={draft.ambience_enabled}
              disabled={!draft.music_enabled}
              onChange={(event) => edit("ambience_enabled", event.currentTarget.checked)}
            />
            <Text size="xs" c="dimmed">
              Ambience is the background beds and the sounds made for points in the music. When
              off, the video is rendered with the score and hits only; the music does not have to
              be placed again.
            </Text>
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
                Sent to the video model. Multiples of 64 only.
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
