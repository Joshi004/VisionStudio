import { useState } from "react";
import {
  Button,
  Group,
  Paper,
  Radio,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import type { MusicBibleInput, MusicBibleOut, MusicBibleState } from "../../api/musicBible";
import { EditorActions, StringListInput } from "../story/editorParts";

type MusicBibleEditorProps = {
  /** The newest Music Bible; the form starts from it. */
  initial: MusicBibleOut["content"];
  /** The scenes, characters and places a theme or an arc line can point to, and the theme cap. */
  state: Pick<MusicBibleState, "scenes" | "characters" | "places" | "max_themes" | "explainer">;
  saving: boolean;
  error: unknown;
  onSave: (content: MusicBibleInput) => void;
  onCancel: () => void;
};

// The section roles and energy levels of an explainer's arc (`ARC_ROLES`, `ARC_ENERGIES` in
// `services/music_bible_writer.py`). The server checks them.
const ROLE_OPTIONS = [
  "hook",
  "setup",
  "explain",
  "evidence",
  "tension",
  "reveal",
  "takeaway",
  "outro",
];
const ENERGY_OPTIONS = ["low", "medium", "high"];

const KIND_OPTIONS = [
  { value: "character", label: "A character" },
  { value: "place", label: "A place" },
  { value: "idea", label: "An idea" },
];

/**
 * The Music Bible as a form. The four directions and the choice are not edited here: the
 * server keeps them from the version being edited. Theme ids are set by the server. It checks
 * the sizes, that exactly one theme is the main one, the theme cap and that the arc covers each
 * scene once, and says which field is wrong.
 */
export function MusicBibleEditor({
  initial,
  state,
  saving,
  error,
  onSave,
  onCancel,
}: MusicBibleEditorProps) {
  // Only the fields that can be written: the server refuses a field it does not know.
  const [draft, setDraft] = useState<MusicBibleInput>({
    concept: initial.concept,
    sound_world: {
      instruments: [...initial.sound_world.instruments],
      avoid: [...initial.sound_world.avoid],
    },
    musical_feel: { ...initial.musical_feel },
    // An explainer's Bible has no themes: the server stores an empty list.
    themes: state.explainer
      ? []
      : initial.themes.map((theme) => ({
          name: theme.name,
          main: theme.main,
          stands_for: {
            kind: theme.stands_for.kind,
            ref: theme.stands_for.ref,
            description: theme.stands_for.description,
          },
          signature_instrument: theme.signature_instrument,
          emotions: [...theme.emotions],
        })),
    // One line per scene, in the story's order.
    arc: state.scenes.map((scene) => {
      const entry = initial.arc.find((item) => item.scene_id === scene.id);
      const music = entry?.music ?? "";
      // A story's arc line is only a scene and a sentence. An explainer's also has a role and
      // an energy; an older story-style Bible starts from a middle choice.
      return state.explainer
        ? {
            scene_id: scene.id,
            role: entry?.role ?? "explain",
            energy: entry?.energy ?? "medium",
            music,
          }
        : { scene_id: scene.id, music };
    }),
    restraint: {
      amount: initial.restraint.amount,
      silence_rules: [...initial.restraint.silence_rules],
    },
    ambience_signature: initial.ambience_signature,
  });
  const change = (part: Partial<MusicBibleInput>) => setDraft({ ...draft, ...part });

  type Theme = MusicBibleInput["themes"][number];
  const changeTheme = (index: number, part: Partial<Theme>) =>
    change({
      themes: draft.themes.map((theme, position) =>
        position === index ? { ...theme, ...part } : theme,
      ),
    });
  const makeMain = (index: number) =>
    change({
      themes: draft.themes.map((theme, position) => ({
        ...theme,
        main: position === index,
      })),
    });

  const refOptions = (kind: string) =>
    (kind === "place" ? state.places : state.characters).map((item) => ({
      value: item.id,
      label: item.name,
    }));
  const atCap = draft.themes.length >= state.max_themes;

  return (
    <Stack gap="sm">
      <Textarea
        label="Concept"
        autosize
        minRows={2}
        value={draft.concept}
        onChange={(event) => change({ concept: event.currentTarget.value })}
      />

      <StringListInput
        label="Instruments"
        hint="The instruments and sound sources the score is made of."
        values={draft.sound_world.instruments}
        addLabel="Add an instrument"
        onChange={(instruments) => change({ sound_world: { ...draft.sound_world, instruments } })}
      />
      <StringListInput
        label="Avoid"
        hint="Sounds the score must never use. None is fine."
        values={draft.sound_world.avoid}
        addLabel="Add something to avoid"
        onChange={(avoid) => change({ sound_world: { ...draft.sound_world, avoid } })}
      />

      <TextInput
        label="Tempo"
        value={draft.musical_feel.tempo}
        onChange={(event) =>
          change({
            musical_feel: {
              ...draft.musical_feel,
              tempo: event.currentTarget.value,
            },
          })
        }
      />
      <TextInput
        label="Mode leaning"
        value={draft.musical_feel.mode_leaning}
        onChange={(event) =>
          change({
            musical_feel: {
              ...draft.musical_feel,
              mode_leaning: event.currentTarget.value,
            },
          })
        }
      />
      <TextInput
        label="Density"
        value={draft.musical_feel.density}
        onChange={(event) =>
          change({
            musical_feel: {
              ...draft.musical_feel,
              density: event.currentTarget.value,
            },
          })
        }
      />

      {!state.explainer && (
        <Stack gap="xs">
          <Text size="sm" fw={500}>
            Themes
          </Text>
          <Text size="xs" c="dimmed">
            Exactly one main theme, and at most {state.max_themes} themes. A theme stands for a
            character, a place or an idea.
          </Text>
          {draft.themes.map((theme, index) => (
            <Paper key={index} withBorder p="sm" radius="md">
              <Stack gap="xs">
                <Group align="flex-end" wrap="nowrap">
                  <TextInput
                    label="Name"
                    value={theme.name}
                    onChange={(event) => changeTheme(index, { name: event.currentTarget.value })}
                    style={{ flex: 1 }}
                  />
                  <Radio
                    label="Main theme"
                    name="main-theme"
                    checked={theme.main}
                    onChange={() => makeMain(index)}
                    pb={6}
                  />
                  <Button
                    variant="default"
                    aria-label={`Remove theme ${index + 1}`}
                    onClick={() =>
                      change({
                        themes: draft.themes.filter((_, position) => position !== index),
                      })
                    }
                  >
                    Remove
                  </Button>
                </Group>
                <Group grow align="flex-start">
                  <Select
                    label="Stands for"
                    allowDeselect={false}
                    data={KIND_OPTIONS}
                    value={theme.stands_for.kind}
                    onChange={(kind) =>
                      kind !== null &&
                      changeTheme(index, {
                        stands_for: { ...theme.stands_for, kind, ref: null },
                      })
                    }
                  />
                  {theme.stands_for.kind !== "idea" && (
                    <Select
                      label={theme.stands_for.kind === "place" ? "Place" : "Character"}
                      placeholder="Choose one"
                      allowDeselect={false}
                      data={refOptions(theme.stands_for.kind)}
                      value={theme.stands_for.ref ?? null}
                      onChange={(ref) =>
                        changeTheme(index, {
                          stands_for: { ...theme.stands_for, ref },
                        })
                      }
                    />
                  )}
                </Group>
                <Textarea
                  label="What it means"
                  autosize
                  minRows={1}
                  value={theme.stands_for.description}
                  onChange={(event) =>
                    changeTheme(index, {
                      stands_for: {
                        ...theme.stands_for,
                        description: event.currentTarget.value,
                      },
                    })
                  }
                />
                <TextInput
                  label="Signature instrument"
                  value={theme.signature_instrument}
                  onChange={(event) =>
                    changeTheme(index, {
                      signature_instrument: event.currentTarget.value,
                    })
                  }
                />
                <StringListInput
                  label="Emotions"
                  hint="The feelings this theme carries."
                  values={theme.emotions}
                  addLabel="Add an emotion"
                  onChange={(emotions) => changeTheme(index, { emotions })}
                />
              </Stack>
            </Paper>
          ))}
          <Group>
            <Button
              variant="default"
              size="xs"
              disabled={atCap}
              onClick={() =>
                change({
                  themes: [
                    ...draft.themes,
                    {
                      name: "",
                      main: draft.themes.length === 0,
                      stands_for: { kind: "idea", ref: null, description: "" },
                      signature_instrument: "",
                      emotions: [],
                    },
                  ],
                })
              }
            >
              Add a theme
            </Button>
          </Group>
        </Stack>
      )}

      <Stack gap="xs">
        <Text size="sm" fw={500}>
          {state.explainer ? "Section arc" : "Arc"}
        </Text>
        <Text size="xs" c="dimmed">
          {state.explainer
            ? "The role, the energy and what the music does in each section, in the script's order."
            : "What the music does in each scene, in the story's order."}
        </Text>
        {draft.arc.map((entry, index) => {
          const changeEntry = (part: Partial<typeof entry>) =>
            change({
              arc: draft.arc.map((item, position) =>
                position === index ? { ...item, ...part } : item,
              ),
            });
          return (
            <Stack key={entry.scene_id} gap={4}>
              {state.explainer && (
                <Group grow align="flex-end">
                  <Select
                    label={
                      state.scenes.find((scene) => scene.id === entry.scene_id)?.title ??
                      entry.scene_id
                    }
                    description="Role"
                    allowDeselect={false}
                    data={ROLE_OPTIONS}
                    value={entry.role ?? null}
                    onChange={(role) => role !== null && changeEntry({ role })}
                  />
                  <Select
                    description="Energy"
                    allowDeselect={false}
                    data={ENERGY_OPTIONS}
                    value={entry.energy ?? null}
                    onChange={(energy) => energy !== null && changeEntry({ energy })}
                  />
                </Group>
              )}
              <Textarea
                label={
                  state.explainer
                    ? undefined
                    : (state.scenes.find((scene) => scene.id === entry.scene_id)?.title ??
                      entry.scene_id)
                }
                aria-label={state.explainer ? "What the music does" : undefined}
                autosize
                minRows={1}
                value={entry.music}
                onChange={(event) => changeEntry({ music: event.currentTarget.value })}
              />
            </Stack>
          );
        })}
      </Stack>

      <Textarea
        label="How much music"
        autosize
        minRows={1}
        value={draft.restraint.amount}
        onChange={(event) =>
          change({
            restraint: {
              ...draft.restraint,
              amount: event.currentTarget.value,
            },
          })
        }
      />
      <StringListInput
        label="Silence rules"
        hint="When the music must stop or stay out. None is fine."
        values={draft.restraint.silence_rules}
        addLabel="Add a silence rule"
        onChange={(silence_rules) => change({ restraint: { ...draft.restraint, silence_rules } })}
      />
      {!state.explainer && (
        <Textarea
          label="Ambience signature"
          autosize
          minRows={1}
          value={draft.ambience_signature}
          onChange={(event) => change({ ambience_signature: event.currentTarget.value })}
        />
      )}

      <Text size="xs" c="dimmed">
        Saving adds a new version written by you. The four directions and the choice stay as they
        were.
      </Text>
      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the Music Bible"
        onSave={() => onSave(draft)}
        onCancel={onCancel}
      />
    </Stack>
  );
}
