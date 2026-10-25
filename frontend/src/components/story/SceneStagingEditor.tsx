import { useState } from "react";
import { Button, Group, Paper, Select, Stack, Text, TextInput } from "@mantine/core";

import type {
  SceneStagingContent,
  StagingEnvironment,
  StagingMove,
  StagingPlacement,
  StagingSaveInput,
} from "../../api/sceneStaging";
import { EditorActions } from "./editorParts";

type SceneStagingEditorProps = {
  /** The scene's newest staging; the form starts from it. */
  initial: SceneStagingContent;
  /** The story's characters, for the names. */
  characters: { id: string; name: string }[];
  /** The scene's environment, for its zones; None when it is not known. */
  environment: StagingEnvironment | null;
  saving: boolean;
  error: unknown;
  onSave: (staging: StagingSaveInput) => void;
  onCancel: () => void;
};

const SIDES = ["ahead", "left", "right", "behind"];
const SCREEN_SIDES = ["left", "right", "center"];

const sideOptions = SIDES.map((value) => ({ value, label: value }));
const screenOptions = SCREEN_SIDES.map((value) => ({ value, label: value }));

/**
 * One scene's staging as a form: the zone, posture, what each character faces, their side of
 * the screen and what is behind them, the group's background, the axis and the moves. The
 * server checks everything the way it checks the model's answer, and says what is wrong.
 */
export function SceneStagingEditor({
  initial,
  characters,
  environment,
  saving,
  error,
  onSave,
  onCancel,
}: SceneStagingEditorProps) {
  const [placements, setPlacements] = useState<StagingPlacement[]>(initial.placements);
  const [groupSide, setGroupSide] = useState<string>(initial.group_side);
  const [between, setBetween] = useState<string[]>(initial.axis.between);
  const [cameraHalf, setCameraHalf] = useState<string | null>(initial.axis.camera_half);
  const [note, setNote] = useState(initial.axis.note);
  const [moves, setMoves] = useState<StagingMove[]>(initial.moves);

  const nameOf = (id: string) => characters.find((item) => item.id === id)?.name ?? id;
  const zoneOptions = (environment?.zones ?? []).map((zone) => ({
    value: zone.id,
    label: `${zone.name} (${zone.side})`,
  }));
  const placed = placements.map((item) => item.character_id);
  const facesOptions = [
    ...SIDES.map((value) => ({ value, label: `Side: ${value}` })),
    ...(environment?.zones ?? []).map((zone) => ({ value: zone.id, label: `Zone: ${zone.name}` })),
    ...placed.map((id) => ({ value: id, label: `Character: ${nameOf(id)}` })),
  ];
  const characterOptions = placed.map((id) => ({ value: id, label: nameOf(id) }));

  const changePlacement = (index: number, part: Partial<StagingPlacement>) =>
    setPlacements(placements.map((item, position) => (position === index ? { ...item, ...part } : item)));
  const changeMove = (index: number, part: Partial<StagingMove>) =>
    setMoves(moves.map((item, position) => (position === index ? { ...item, ...part } : item)));

  const save = () =>
    onSave({
      placements,
      // Who is only heard is decided by the scene's definition and the model; it is kept as it is.
      off_screen: initial.off_screen ?? [],
      axis: { between, camera_half: between.length === 2 ? cameraHalf : null, note },
      group_side: groupSide,
      moves,
    });

  return (
    <Stack gap="sm">
      {placements.map((placement, index) => (
        <Paper key={placement.character_id} withBorder p="sm" radius="sm">
          <Stack gap="xs">
            <Text size="sm" fw={600}>
              {nameOf(placement.character_id)}
            </Text>
            <Group gap="xs" align="flex-end" grow>
              <Select
                label="Zone"
                data={zoneOptions}
                value={placement.zone}
                allowDeselect={false}
                onChange={(value) => value !== null && changePlacement(index, { zone: value })}
              />
              <Select
                label="Faces"
                data={facesOptions.filter((option) => option.value !== placement.character_id)}
                value={placement.faces}
                allowDeselect={false}
                onChange={(value) => value !== null && changePlacement(index, { faces: value })}
              />
              <Select
                label="Screen side"
                data={screenOptions}
                value={placement.screen_side}
                allowDeselect={false}
                onChange={(value) =>
                  value !== null &&
                  changePlacement(index, { screen_side: value as StagingPlacement["screen_side"] })
                }
              />
              <Select
                label="Behind them"
                data={sideOptions}
                value={placement.background_side}
                allowDeselect={false}
                onChange={(value) =>
                  value !== null &&
                  changePlacement(index, {
                    background_side: value as StagingPlacement["background_side"],
                  })
                }
              />
            </Group>
            <TextInput
              label="Posture"
              value={placement.posture}
              onChange={(event) => changePlacement(index, { posture: event.currentTarget.value })}
            />
          </Stack>
        </Paper>
      ))}
      {(initial.off_screen ?? []).length > 0 && (
        <Text size="sm" c="dimmed">
          Only heard, not placed: {(initial.off_screen ?? []).map(nameOf).join(", ")}
        </Text>
      )}
      <Group gap="xs" align="flex-end" grow>
        <Select
          label="Group background"
          description="Seen behind everyone in a two-shot or a wide shot."
          data={sideOptions}
          value={groupSide}
          allowDeselect={false}
          onChange={(value) => value !== null && setGroupSide(value)}
        />
        {placed.length >= 2 && (
          <>
            <Select
              label="Axis: first character"
              data={characterOptions}
              value={between[0] ?? null}
              onChange={(value) => value !== null && setBetween([value, between[1] ?? ""])}
            />
            <Select
              label="Axis: second character"
              data={characterOptions}
              value={between[1] ?? null}
              onChange={(value) => value !== null && setBetween([between[0] ?? "", value])}
            />
            <Select
              label="Camera stays on the side"
              data={sideOptions}
              value={cameraHalf}
              onChange={setCameraHalf}
            />
          </>
        )}
      </Group>
      <TextInput
        label="Axis note"
        description="Optional: one line on how the conversation is covered."
        value={note}
        onChange={(event) => setNote(event.currentTarget.value)}
      />
      {moves.map((move, index) => (
        <Paper key={index} withBorder p="sm" radius="sm">
          <Stack gap="xs">
            <Group gap="xs" align="flex-end" grow>
              <TextInput
                label={`Move ${index + 1}: after event`}
                value={move.after_event_id}
                onChange={(event) => changeMove(index, { after_event_id: event.currentTarget.value })}
              />
              <Select
                label="Character"
                data={characterOptions}
                value={move.character_id}
                allowDeselect={false}
                onChange={(value) => value !== null && changeMove(index, { character_id: value })}
              />
              <Select
                label="Zone"
                data={zoneOptions}
                value={move.zone}
                allowDeselect={false}
                onChange={(value) => value !== null && changeMove(index, { zone: value })}
              />
            </Group>
            <Group gap="xs" align="flex-end" grow>
              <Select
                label="Faces"
                data={facesOptions.filter((option) => option.value !== move.character_id)}
                value={move.faces}
                allowDeselect={false}
                onChange={(value) => value !== null && changeMove(index, { faces: value })}
              />
              <Select
                label="Screen side"
                data={screenOptions}
                value={move.screen_side}
                allowDeselect={false}
                onChange={(value) =>
                  value !== null &&
                  changeMove(index, { screen_side: value as StagingMove["screen_side"] })
                }
              />
              <Select
                label="Behind them"
                data={sideOptions}
                value={move.background_side}
                allowDeselect={false}
                onChange={(value) =>
                  value !== null &&
                  changeMove(index, { background_side: value as StagingMove["background_side"] })
                }
              />
              <Button
                variant="default"
                aria-label={`Remove move ${index + 1}`}
                onClick={() => setMoves(moves.filter((_, position) => position !== index))}
              >
                Remove
              </Button>
            </Group>
          </Stack>
        </Paper>
      ))}
      {placed.length > 0 && environment !== null && (
        <Group>
          <Button
            variant="default"
            onClick={() =>
              setMoves([
                ...moves,
                {
                  after_event_id: "",
                  character_id: placed[0],
                  zone: environment.zones[0]?.id ?? "",
                  faces: "ahead",
                  screen_side: "center",
                  background_side: "behind",
                },
              ])
            }
          >
            Add a move
          </Button>
        </Group>
      )}
      <Text size="xs" c="dimmed">
        Saving adds a new version written by you. The shots after it will say they are out of date.
      </Text>
      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the scene staging"
        onSave={save}
        onCancel={onCancel}
      />
    </Stack>
  );
}
