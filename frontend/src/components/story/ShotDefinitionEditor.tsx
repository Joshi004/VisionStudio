import { useState } from "react";
import type { ReactNode } from "react";
import {
  Button,
  Checkbox,
  Group,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import type {
  ShotDefinitionContent,
  ShotDefinitionInput,
  ShotStaging,
} from "../../api/shotDefinitions";
import { EditorActions, StringListInput } from "./editorParts";

type ShotDefinitionEditorProps = {
  /** The shot's newest specification; the form starts from it. */
  initial: ShotDefinitionContent;
  /** The views that may stand behind this shot; null when the scene is not staged. */
  staging: ShotStaging | null;
  /** The ids of the scene's characters: only these can be on screen or tracked. */
  sceneCharacterIds: string[];
  /** The story's characters by id, so a character is shown by name. */
  characterNames: Record<string, string>;
  saving: boolean;
  error: unknown;
  onSave: (definition: ShotDefinitionInput) => void;
  onCancel: () => void;
};

/** The allowed shot sizes, from the tightest to the widest (`shot_definition_writer.SHOT_SIZES`). */
const SHOT_SIZES = [
  "extreme_close_up",
  "close_up",
  "medium_close_up",
  "medium",
  "medium_wide",
  "wide",
  "extreme_wide",
];

// The lengths the model is asked to keep to (`shot_definition_writer`). The server accepts a
// little more, so these are the safe side.
const LIMIT = {
  visualStory: 300,
  expression: 240,
  pose: 300,
  gaze: 200,
  stateValue: 120,
  composition: 200,
  camera: 160,
  action: 250,
  continuity: 200,
  ambient: 200,
  soundEvent: 150,
};
const MAX_SOUND_EVENTS = 8;
const MAX_STATE_KEYS = 12;
const STATE_KEY = /^[a-z][a-z0-9_]{0,39}$/;

type CharacterRow = {
  id: string;
  expression: string;
  pose: string;
  gaze: string;
};

/** One entry of the environment state: a true or false stays a switch, anything else is text. */
type StateRow = { key: string; value: string | boolean };

type Draft = {
  visualStory: string;
  characters: CharacterRow[];
  environment: StateRow[];
  shotSize: string;
  angle: string;
  focus: string;
  view: string;
  movement: string;
  intensity: string;
  startState: string;
  primaryAction: string;
  endState: string;
  continuityStart: Record<string, string>;
  continuityEnd: Record<string, string>;
  ambient: string;
  soundEvents: string[];
};

function toDraft(definition: ShotDefinitionContent): Draft {
  return {
    visualStory: definition.visual_story,
    characters: definition.characters.map((character) => ({ ...character })),
    environment: Object.entries(definition.environment_state).map(
      ([key, value]) => ({ key, value }),
    ),
    shotSize: definition.composition.shot_size,
    angle: definition.composition.angle,
    focus: definition.composition.focus,
    view: definition.composition.view ?? "",
    movement: definition.camera.movement,
    intensity: definition.camera.intensity,
    startState: definition.action.start_state,
    primaryAction: definition.action.primary_action,
    endState: definition.action.end_state,
    continuityStart: { ...definition.continuity_start },
    continuityEnd: { ...definition.continuity_end },
    ambient: definition.audio_intent.ambient,
    soundEvents: [...definition.audio_intent.sound_events],
  };
}

/** The continuity notes that have words: an empty note means "nothing tracked" and is left out. */
function nonEmpty(notes: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(notes)
      .map(([id, text]) => [id, text.trim()] as const)
      .filter(([, text]) => text !== ""),
  );
}

function toInput(draft: Draft): ShotDefinitionInput {
  return {
    visual_story: draft.visualStory.trim(),
    characters: draft.characters.map((character) => ({
      id: character.id,
      expression: character.expression.trim(),
      pose: character.pose.trim(),
      gaze: character.gaze.trim(),
    })),
    environment_state: Object.fromEntries(
      draft.environment.map((row) => [
        row.key.trim(),
        typeof row.value === "string" ? row.value.trim() : row.value,
      ]),
    ),
    composition: {
      shot_size: draft.shotSize,
      angle: draft.angle.trim(),
      focus: draft.focus.trim(),
      view: draft.view === "" ? null : draft.view,
    },
    camera: {
      movement: draft.movement.trim(),
      intensity: draft.intensity.trim(),
    },
    action: {
      start_state: draft.startState.trim(),
      primary_action: draft.primaryAction.trim(),
      end_state: draft.endState.trim(),
    },
    continuity_start: nonEmpty(draft.continuityStart),
    continuity_end: nonEmpty(draft.continuityEnd),
    audio_intent: {
      ambient: draft.ambient.trim(),
      sound_events: draft.soundEvents
        .map((text) => text.trim())
        .filter((text) => text !== ""),
    },
  };
}

/**
 * The views that may stand behind the shot: a single of one character (the focus is that
 * character's id and the shot is not a wide one) takes the views allowed for that character; any
 * other shot takes the views allowed for the group. The server decides in the end.
 */
function allowedViews(draft: Draft, staging: ShotStaging) {
  const single =
    !draft.shotSize.includes("wide") &&
    draft.characters.some((character) => character.id === draft.focus.trim());
  const key = single ? draft.focus.trim() : "group";
  return staging.views.filter((view) => view.allowed_for.includes(key));
}

/** Whether every field the server needs has words. The server checks the rest. */
function isComplete(draft: Draft, staging: ShotStaging | null): boolean {
  const required = [
    draft.visualStory,
    draft.angle,
    draft.focus,
    draft.movement,
    draft.intensity,
    draft.startState,
    draft.primaryAction,
    draft.endState,
    draft.ambient,
    ...draft.characters.flatMap((c) => [c.expression, c.pose, c.gaze]),
  ];
  const keys = draft.environment.map((row) => row.key.trim());
  return (
    (staging === null || draft.view !== "") &&
    required.every((text) => text.trim() !== "") &&
    keys.every((key) => STATE_KEY.test(key)) &&
    new Set(keys).size === keys.length &&
    draft.environment.every(
      (row) => typeof row.value === "boolean" || row.value.trim() !== "",
    )
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Stack gap={6}>
      <Text size="xs" fw={600} c="dimmed" tt="uppercase">
        {title}
      </Text>
      {children}
    </Stack>
  );
}

type TextFieldProps = {
  label: string;
  value: string;
  maxLength: number;
  onChange: (value: string) => void;
};

/** One phrase of the specification, with the length the model is asked to keep to. */
function TextField({ label, value, maxLength, onChange }: TextFieldProps) {
  return (
    <Textarea
      label={label}
      size="xs"
      autosize
      minRows={1}
      maxLength={maxLength}
      value={value}
      onChange={(event) => onChange(event.currentTarget.value)}
    />
  );
}

/**
 * One shot's cinematic specification, edited by hand. Every field the model writes can change.
 * The id, the length and the dialogue are written by code from the plan and the timeline, so
 * they are not here. The server checks the result like it checks the model's answer: the
 * characters must be ones of the scene, and a state key must be lower_case_with_underscores.
 */
export function ShotDefinitionEditor({
  initial,
  staging,
  sceneCharacterIds,
  characterNames,
  saving,
  error,
  onSave,
  onCancel,
}: ShotDefinitionEditorProps) {
  const [draft, setDraft] = useState<Draft>(toDraft(initial));
  const [adding, setAdding] = useState<string | null>(null);

  const change = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });
  const nameOf = (id: string) => characterNames[id] ?? id;

  // The characters the scene has, plus any the specification already names.
  const knownIds = [
    ...new Set([
      ...sceneCharacterIds,
      ...initial.characters.map((character) => character.id),
      ...Object.keys(initial.continuity_start),
      ...Object.keys(initial.continuity_end),
    ]),
  ];
  const addable = knownIds.filter(
    (id) => !draft.characters.some((character) => character.id === id),
  );

  const changeCharacter = (index: number, patch: Partial<CharacterRow>) =>
    change({
      characters: draft.characters.map((character, position) =>
        position === index ? { ...character, ...patch } : character,
      ),
    });
  const changeState = (index: number, patch: Partial<StateRow>) =>
    change({
      environment: draft.environment.map((row, position) =>
        position === index ? { ...row, ...patch } : row,
      ),
    });

  return (
    <Stack gap="md">
      <TextField
        label="Visual story"
        value={draft.visualStory}
        maxLength={LIMIT.visualStory}
        onChange={(value) => change({ visualStory: value })}
      />

      <Section title="Characters on screen">
        {draft.characters.length === 0 && (
          <Text size="sm" c="dimmed">
            Nobody is visible.
          </Text>
        )}
        {draft.characters.map((character, index) => (
          <Paper key={character.id} withBorder p="sm" radius="sm">
            <Stack gap="xs">
              <Group justify="space-between">
                <Text size="sm" fw={500}>
                  {nameOf(character.id)}
                </Text>
                <Button
                  size="compact-xs"
                  variant="default"
                  onClick={() =>
                    change({
                      characters: draft.characters.filter(
                        (_, position) => position !== index,
                      ),
                    })
                  }
                >
                  Remove
                </Button>
              </Group>
              <TextField
                label="Expression"
                value={character.expression}
                maxLength={LIMIT.expression}
                onChange={(value) =>
                  changeCharacter(index, { expression: value })
                }
              />
              <TextField
                label="Pose"
                value={character.pose}
                maxLength={LIMIT.pose}
                onChange={(value) => changeCharacter(index, { pose: value })}
              />
              <TextField
                label="Gaze"
                value={character.gaze}
                maxLength={LIMIT.gaze}
                onChange={(value) => changeCharacter(index, { gaze: value })}
              />
            </Stack>
          </Paper>
        ))}
        {addable.length > 0 && (
          <Group gap="xs" align="flex-end">
            <Select
              aria-label="Character to add"
              placeholder="Add a character of the scene"
              size="xs"
              data={addable.map((id) => ({ value: id, label: nameOf(id) }))}
              value={adding}
              onChange={setAdding}
              w={260}
            />
            <Button
              size="xs"
              variant="default"
              disabled={adding === null}
              onClick={() => {
                if (adding !== null) {
                  change({
                    characters: [
                      ...draft.characters,
                      { id: adding, expression: "", pose: "", gaze: "" },
                    ],
                  });
                  setAdding(null);
                }
              }}
            >
              Add
            </Button>
          </Group>
        )}
      </Section>

      <Section title="Composition and camera">
        <Select
          label="Shot size"
          size="xs"
          allowDeselect={false}
          data={SHOT_SIZES.map((size) => ({
            value: size,
            label: size.replaceAll("_", " "),
          }))}
          value={draft.shotSize}
          onChange={(value) => {
            if (value !== null) {
              change({ shotSize: value });
            }
          }}
          w={260}
        />
        <TextField
          label="Angle"
          value={draft.angle}
          maxLength={LIMIT.composition}
          onChange={(value) => change({ angle: value })}
        />
        <TextField
          label="Focus"
          value={draft.focus}
          maxLength={LIMIT.composition}
          onChange={(value) => change({ focus: value })}
        />
        {staging !== null && (
          <Select
            label="View behind the shot"
            description="A single shot of one character takes a view that covers that character's background; a shot of the group takes a group view."
            size="xs"
            data={allowedViews(draft, staging).map((view) => ({
              value: view.id,
              label: `${view.name} (${view.side})`,
            }))}
            value={draft.view === "" ? null : draft.view}
            onChange={(value) => change({ view: value ?? "" })}
            w={360}
          />
        )}
        <TextField
          label="Camera movement"
          value={draft.movement}
          maxLength={LIMIT.camera}
          onChange={(value) => change({ movement: value })}
        />
        <TextField
          label="Camera intensity"
          value={draft.intensity}
          maxLength={LIMIT.camera}
          onChange={(value) => change({ intensity: value })}
        />
      </Section>

      <Section title="Action">
        <TextField
          label="Starts"
          value={draft.startState}
          maxLength={LIMIT.action}
          onChange={(value) => change({ startState: value })}
        />
        <TextField
          label="Happens"
          value={draft.primaryAction}
          maxLength={LIMIT.action}
          onChange={(value) => change({ primaryAction: value })}
        />
        <TextField
          label="Ends"
          value={draft.endState}
          maxLength={LIMIT.action}
          onChange={(value) => change({ endState: value })}
        />
      </Section>

      <Section title="Environment state">
        <Text size="xs" c="dimmed">
          One entry per aspect of the place, such as lighting. A key is
          lower_case_with_underscores.
        </Text>
        {draft.environment.map((row, index) => (
          <Group key={index} gap="xs" wrap="nowrap" align="flex-start">
            <TextInput
              aria-label={`Environment key ${index + 1}`}
              size="xs"
              value={row.key}
              error={
                row.key.trim() !== "" && !STATE_KEY.test(row.key.trim())
                  ? "lower_case_with_underscores"
                  : undefined
              }
              onChange={(event) =>
                changeState(index, { key: event.currentTarget.value })
              }
              w={200}
            />
            {typeof row.value === "boolean" ? (
              <Checkbox
                aria-label={`Environment value ${index + 1}`}
                label={row.value ? "true" : "false"}
                checked={row.value}
                onChange={(event) =>
                  changeState(index, { value: event.currentTarget.checked })
                }
                mt={4}
                style={{ flex: 1 }}
              />
            ) : (
              <TextInput
                aria-label={`Environment value ${index + 1}`}
                size="xs"
                maxLength={LIMIT.stateValue}
                value={row.value}
                onChange={(event) =>
                  changeState(index, { value: event.currentTarget.value })
                }
                style={{ flex: 1 }}
              />
            )}
            <Button
              size="compact-xs"
              variant="default"
              mt={4}
              onClick={() =>
                change({
                  environment: draft.environment.filter(
                    (_, position) => position !== index,
                  ),
                })
              }
            >
              Remove
            </Button>
          </Group>
        ))}
        <Group>
          <Button
            size="xs"
            variant="default"
            disabled={draft.environment.length >= MAX_STATE_KEYS}
            onClick={() =>
              change({
                environment: [...draft.environment, { key: "", value: "" }],
              })
            }
          >
            Add an entry
          </Button>
        </Group>
      </Section>

      <Section title="Continuity">
        <Text size="xs" c="dimmed">
          How each character looks where the shot starts and ends. Leave a note
          empty to track nothing for that character.
        </Text>
        {knownIds.map((id) => (
          <Group key={id} gap="xs" align="flex-start" grow>
            <TextField
              label={`${nameOf(id)}, at the start`}
              value={draft.continuityStart[id] ?? ""}
              maxLength={LIMIT.continuity}
              onChange={(value) =>
                change({
                  continuityStart: { ...draft.continuityStart, [id]: value },
                })
              }
            />
            <TextField
              label={`${nameOf(id)}, at the end`}
              value={draft.continuityEnd[id] ?? ""}
              maxLength={LIMIT.continuity}
              onChange={(value) =>
                change({
                  continuityEnd: { ...draft.continuityEnd, [id]: value },
                })
              }
            />
          </Group>
        ))}
      </Section>

      <Section title="Audio intent">
        <TextField
          label="Ambient"
          value={draft.ambient}
          maxLength={LIMIT.ambient}
          onChange={(value) => change({ ambient: value })}
        />
        <StringListInput
          label="Sound events"
          hint={`At most ${MAX_SOUND_EVENTS}, each up to ${LIMIT.soundEvent} characters.`}
          values={draft.soundEvents}
          addLabel="Add a sound"
          onChange={(values) =>
            change({ soundEvents: values.slice(0, MAX_SOUND_EVENTS) })
          }
        />
        <Text size="xs" c="dimmed">
          The length and the dialogue come from the timeline and cannot be
          changed here.
        </Text>
      </Section>

      <Text size="xs" c="dimmed">
        Saving adds a new specification written by you. The pictures, the
        request and the prompt of this shot are then worked out again from it,
        except any you wrote yourself, which stay as they are and say they are
        out of date.
      </Text>
      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the shot definition"
        canSave={isComplete(draft, staging)}
        onSave={() => onSave(toInput(draft))}
        onCancel={onCancel}
      />
    </Stack>
  );
}
