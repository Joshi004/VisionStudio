import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  NumberInput,
  Paper,
  Radio,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";

import { useProjectCast } from "../../api/projectCast";
import type { ProjectDetail, ProjectUpdate } from "../../api/projects";
import { capitalise } from "../../format";
import { CALLOUT_STYLES, isCalloutStyle } from "./calloutStyles";
import { CAPTION_MODES, isCaptionMode } from "./captionModes";
import { PresenterOutfitField } from "./PresenterOutfitField";
import { STAGING_MAX_CHARS, projectKindLabel } from "./projectKinds";
import { speechModeLabel } from "./speechModes";
import { DELIVERY_MAX_CHARS, voiceTrackLabel } from "./voiceTracks";
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
  // The presenter's outfits are the ones of the character that was chosen at creation.
  const cast = useProjectCast(project.id);
  const presenterId = cast.data?.characters[0]?.library_id ?? null;
  const changes = changedFields(project, draft);
  const unchanged = Object.keys(changes).length === 0;

  // Motion callouts are only for a continuous explainer with graphics and callouts on.
  const canChooseCalloutStyle =
    project.voice_track === "continuous" && project.graphics && draft.callouts;

  function edit<K extends keyof Draft>(field: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [field]: value }));
    onEdit();
  }

  function editCallouts(on: boolean) {
    // Motion callouts need callouts on, so switching them off puts the style back to boxes in
    // the same save.
    setDraft((current) => ({
      ...current,
      callouts: on,
      callout_style: on ? current.callout_style : "boxes",
    }));
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

        {project.kind === "explainer" && (
          <Paper withBorder p="md" radius="md">
            <Stack gap="xs">
              <Title order={4}>Presenter staging</Title>
              <Textarea
                aria-label="Presenter staging"
                description="How the presenter is placed and moves on camera, for example: seated at a desk, hands on the desk, little movement. Left empty, the presenter stands."
                value={draft.presenter_staging}
                onChange={(event) => edit("presenter_staging", event.currentTarget.value)}
                maxLength={STAGING_MAX_CHARS}
                autosize
                minRows={2}
                maxRows={6}
              />
              <Text size="xs" c="dimmed">
                Every presenter shot is defined with this text, so changing it makes those shots
                out of date. A studio designed from the script uses it only when it is designed:
                design the studio again to change it.
              </Text>
            </Stack>
          </Paper>
        )}

        {project.kind === "explainer" && (
          <Paper withBorder p="md" radius="md">
            <Stack gap="xs">
              <Title order={4}>Presenter outfit</Title>
              <PresenterOutfitField
                characterId={presenterId}
                pickedId={draft.presenter_named_look_id}
                text={draft.presenter_outfit}
                deletedPick={
                  project.presenter_named_look_deleted &&
                  project.presenter_named_look_id !== null &&
                  project.presenter_named_look_id !== undefined
                    ? {
                        id: project.presenter_named_look_id,
                        name: project.presenter_named_look_name ?? "Saved outfit",
                      }
                    : null
                }
                onChange={(value) => {
                  edit("presenter_named_look_id", value.pickedId);
                  edit("presenter_outfit", value.text);
                }}
              />
              <Text size="xs" c="dimmed">
                The outfit is used in every scene. Changing it makes the resolved looks out of
                date, and with them the presenter shots.
              </Text>
            </Stack>
          </Paper>
        )}

        {project.kind === "explainer" && (
          <Paper withBorder p="md" radius="md">
            <Stack gap="xs">
              <Group gap="sm">
                <Title order={4}>Voice</Title>
                <Badge variant="light">{voiceTrackLabel(project.voice_track)}</Badge>
                <Text size="xs" c="dimmed">
                  The voice is fixed after creation.
                </Text>
              </Group>
              {project.voice_track === "continuous" && (
                <>
                  <Textarea
                    label="Presenter delivery"
                    description="How the presenter should sound, for example pace and energy. Left empty, the style from the Story Bible is used, or a default."
                    value={draft.presenter_delivery}
                    onChange={(event) => edit("presenter_delivery", event.currentTarget.value)}
                    maxLength={DELIVERY_MAX_CHARS}
                    autosize
                    minRows={2}
                    maxRows={6}
                  />
                  <Text size="xs" c="dimmed">
                    Every scene's voice take is made with this text, so changing it makes the
                    takes out of date.
                  </Text>
                  <Group gap="sm">
                    <Text size="sm" fw={500}>
                      Graphics
                    </Text>
                    <Badge variant="light" color={project.graphics ? "green" : "gray"}>
                      {project.graphics ? "On" : "Off"}
                    </Badge>
                    <Text size="xs" c="dimmed">
                      Graphics are fixed after creation.
                    </Text>
                  </Group>
                </>
              )}
            </Stack>
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

        {project.kind === "explainer" && (
          <Paper withBorder p="md" radius="md">
            <Stack gap="xs">
              <Title order={4}>Captions and callouts</Title>
              <Radio.Group
                label="Captions"
                value={draft.caption_mode}
                onChange={(value) => {
                  if (isCaptionMode(value)) {
                    edit("caption_mode", value);
                  }
                }}
              >
                <Stack mt="xs" gap="xs">
                  {CAPTION_MODES.map((option) => (
                    <Radio.Card key={option.value} value={option.value} p="md" radius="md">
                      <Group wrap="nowrap" align="flex-start">
                        <Radio.Indicator />
                        <Stack gap={2}>
                          <Text fw={500}>{option.label}</Text>
                          <Text size="sm" c="dimmed">
                            {option.description}
                          </Text>
                        </Stack>
                      </Group>
                    </Radio.Card>
                  ))}
                </Stack>
              </Radio.Group>
              <Switch
                label="Callouts"
                checked={draft.callouts}
                onChange={(event) => editCallouts(event.currentTarget.checked)}
              />
              {canChooseCalloutStyle && (
                <Radio.Group
                  label="Callout style"
                  value={draft.callout_style}
                  onChange={(value) => {
                    if (isCalloutStyle(value)) {
                      edit("callout_style", value);
                    }
                  }}
                >
                  <Stack mt="xs" gap="xs">
                    {CALLOUT_STYLES.map((option) => (
                      <Radio.Card key={option.value} value={option.value} p="md" radius="md">
                        <Group wrap="nowrap" align="flex-start">
                          <Radio.Indicator />
                          <Stack gap={2}>
                            <Text fw={500}>{option.label}</Text>
                            <Text size="sm" c="dimmed">
                              {option.description}
                            </Text>
                          </Stack>
                        </Group>
                      </Radio.Card>
                    ))}
                  </Stack>
                </Radio.Group>
              )}
              <Text size="xs" c="dimmed">
                Both apply when the video is rendered, so they can be changed at any time without
                making anything again. A change marks the videos it no longer fits as out of date.
              </Text>
            </Stack>
          </Paper>
        )}

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
