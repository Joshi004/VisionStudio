import { useState } from "react";
import { Button, Group, Paper, Radio, Select, Stack, Text, TextInput, Textarea } from "@mantine/core";

import type { MusicBibleInput, MusicBibleOut, MusicBibleState } from "../../api/musicBible";
import { EditorActions, StringListInput } from "../story/editorParts";

type MusicBibleEditorProps = {
  /** The newest Music Bible; the form starts from it. */
  initial: MusicBibleOut["content"];
  /** The scenes, characters and places a theme or an arc line can point to, and the theme cap. */
  state: Pick<MusicBibleState, "scenes" | "characters" | "places" | "max_themes">;
  saving: boolean;
  error: unknown;
  onSave: (content: MusicBibleInput) => void;
  onCancel: () => void;
};

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
    themes: initial.themes.map((theme) => ({
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
    arc: state.scenes.map((scene) => ({
      scene_id: scene.id,
      music: initial.arc.find((entry) => entry.scene_id === scene.id)?.music ?? "",
    })),
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
    change({ themes: draft.themes.map((theme, position) => ({ ...theme, main: position === index })) });

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
          change({ musical_feel: { ...draft.musical_feel, tempo: event.currentTarget.value } })
        }
      />
      <TextInput
        label="Mode leaning"
        value={draft.musical_feel.mode_leaning}
        onChange={(event) =>
          change({
            musical_feel: { ...draft.musical_feel, mode_leaning: event.currentTarget.value },
          })
        }
      />
      <TextInput
        label="Density"
        value={draft.musical_feel.density}
        onChange={(event) =>
          change({ musical_feel: { ...draft.musical_feel, density: event.currentTarget.value } })
        }
      />

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
                    change({ themes: draft.themes.filter((_, position) => position !== index) })
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
                      changeTheme(index, { stands_for: { ...theme.stands_for, ref } })
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
                    stands_for: { ...theme.stands_for, description: event.currentTarget.value },
                  })
                }
              />
              <TextInput
                label="Signature instrument"
                value={theme.signature_instrument}
                onChange={(event) =>
                  changeTheme(index, { signature_instrument: event.currentTarget.value })
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

      <Stack gap="xs">
        <Text size="sm" fw={500}>
          Arc
        </Text>
        <Text size="xs" c="dimmed">
          What the music does in each scene, in the story's order.
        </Text>
        {draft.arc.map((entry, index) => (
          <Textarea
            key={entry.scene_id}
            label={state.scenes.find((scene) => scene.id === entry.scene_id)?.title ?? entry.scene_id}
            autosize
            minRows={1}
            value={entry.music}
            onChange={(event) => {
              const music = event.currentTarget.value;
              change({
                arc: draft.arc.map((item, position) =>
                  position === index ? { ...item, music } : item,
                ),
              });
            }}
          />
        ))}
      </Stack>

      <Textarea
        label="How much music"
        autosize
        minRows={1}
        value={draft.restraint.amount}
        onChange={(event) =>
          change({ restraint: { ...draft.restraint, amount: event.currentTarget.value } })
        }
      />
      <StringListInput
        label="Silence rules"
        hint="When the music must stop or stay out. None is fine."
        values={draft.restraint.silence_rules}
        addLabel="Add a silence rule"
        onChange={(silence_rules) => change({ restraint: { ...draft.restraint, silence_rules } })}
      />
      <Textarea
        label="Ambience signature"
        autosize
        minRows={1}
        value={draft.ambience_signature}
        onChange={(event) => change({ ambience_signature: event.currentTarget.value })}
      />

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
