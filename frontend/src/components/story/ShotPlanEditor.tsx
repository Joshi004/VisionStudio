import { useState } from "react";
import {
  Badge,
  Checkbox,
  Group,
  MultiSelect,
  NumberInput,
  Paper,
  Select,
  Stack,
  Text,
  Textarea,
} from "@mantine/core";

import type { SceneEventsContent } from "../../api/sceneEvents";
import type { SpeechUnitsContent } from "../../api/speechUnits";
import type { Shot, ShotInput, ShotPlanContent } from "../../api/shotPlans";
import { EditorActions } from "./editorParts";
import { SHOT_TYPE, SHOT_TYPES, eventText, unitText } from "./shotPlanFormat";

type ShotPlanEditorProps = {
  /** The scene's newest plan; the form starts from it. */
  initial: ShotPlanContent;
  /** The scene's events and speech units, to choose what each shot shows and carries. */
  events: SceneEventsContent | null;
  units: SpeechUnitsContent | null;
  /** The story's characters by id, so a speaker is shown by name. */
  characterNames: Record<string, string>;
  saving: boolean;
  error: unknown;
  onSave: (plan: { shots: ShotInput[] }) => void;
  onCancel: () => void;
};

/** One shot being edited. The length is kept as typed, so a half-typed number is not lost. */
type ShotDraft = {
  id: string;
  type: Shot["type"];
  targetDuration: number | string;
  continuesPrevious: boolean;
  rapidExchange: boolean;
  description: string;
  eventIds: string[];
  unitIds: string[];
};

function toDraft(shot: Shot): ShotDraft {
  return {
    id: shot.id,
    type: shot.type,
    targetDuration: shot.target_duration,
    continuesPrevious: shot.continues_previous,
    rapidExchange: shot.rapid_exchange,
    description: shot.description,
    eventIds: shot.source_event_ids,
    unitIds: shot.speech_unit_ids,
  };
}

/** The chosen ids put back in the order the scene lists them: the server wants story order. */
function inStoryOrder(chosen: string[], allIds: string[]): string[] {
  return allIds.filter((id) => chosen.includes(id));
}

function isValidDuration(value: number | string): boolean {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

/**
 * One scene's shots, edited by hand. Each shot keeps its id; its type, target length,
 * description and the events and speech it carries can change. Shots cannot be added, removed,
 * split or merged: to change how many there are, plan the scene again. The server checks the
 * result like it checks the model's plan and refuses a save that could not be filmed.
 */
export function ShotPlanEditor({
  initial,
  events,
  units,
  characterNames,
  saving,
  error,
  onSave,
  onCancel,
}: ShotPlanEditorProps) {
  const [shots, setShots] = useState<ShotDraft[]>(initial.shots.map(toDraft));

  const eventOptions = (events?.events ?? []).map((event) => ({
    value: event.id,
    label: `${event.id} \u00B7 ${eventText(event, characterNames)}`,
  }));
  const unitOptions = (units?.units ?? []).map((unit) => ({
    value: unit.id,
    label: `${unit.id} \u00B7 ${unitText(unit, characterNames)}`,
  }));
  const eventIds = eventOptions.map((option) => option.value);
  const unitIds = unitOptions.map((option) => option.value);

  const change = (index: number, patch: Partial<ShotDraft>) =>
    setShots(
      shots.map((shot, position) =>
        position === index ? { ...shot, ...patch } : shot,
      ),
    );

  // The server checks the rest (order, coverage, length of the whole scene); these only keep
  // an obviously unfinished shot from being sent.
  const canSave = shots.every(
    (shot) =>
      isValidDuration(shot.targetDuration) &&
      shot.eventIds.length > 0 &&
      shot.description.trim() !== "",
  );

  const save = () =>
    onSave({
      shots: shots.map((shot) => ({
        type: shot.type,
        target_duration: Number(shot.targetDuration),
        continues_previous: shot.continuesPrevious,
        rapid_exchange: shot.rapidExchange,
        description: shot.description.trim(),
        source_event_ids: shot.eventIds,
        speech_unit_ids: shot.unitIds,
      })),
    });

  return (
    <Stack gap="sm">
      {shots.map((shot, index) => (
        <Paper key={shot.id} withBorder p="sm" radius="sm">
          <Stack gap="xs">
            <Group gap="xs" align="flex-end">
              <Badge
                variant="outline"
                color="gray"
                miw={64}
                style={{ textTransform: "none" }}
              >
                {shot.id}
              </Badge>
              <Select
                label="Type"
                size="xs"
                allowDeselect={false}
                data={SHOT_TYPES.map((type) => ({
                  value: type,
                  label: SHOT_TYPE[type].label,
                }))}
                value={shot.type}
                onChange={(value) => {
                  if (value !== null) {
                    change(index, { type: value as Shot["type"] });
                  }
                }}
                w={150}
              />
              <NumberInput
                label="Target length (s)"
                size="xs"
                description="Moved to the nearest length the video model makes"
                min={0.1}
                step={0.1}
                decimalScale={3}
                allowNegative={false}
                value={shot.targetDuration}
                onChange={(value) => change(index, { targetDuration: value })}
                w={140}
              />
              <Checkbox
                label="Continues the shot before (no cut)"
                size="xs"
                disabled={index === 0}
                checked={shot.continuesPrevious && index > 0}
                onChange={(event) =>
                  change(index, {
                    continuesPrevious: event.currentTarget.checked,
                    // A shot is a continuation or an exchange, never both.
                    rapidExchange: event.currentTarget.checked
                      ? false
                      : shot.rapidExchange,
                  })
                }
              />
              <Checkbox
                label="Rapid exchange (cut at each line)"
                size="xs"
                description="Two or three lines from two speakers who take turns"
                disabled={shot.unitIds.length < 2 || shot.unitIds.length > 3}
                checked={shot.rapidExchange}
                onChange={(event) =>
                  change(index, {
                    rapidExchange: event.currentTarget.checked,
                    continuesPrevious: event.currentTarget.checked
                      ? false
                      : shot.continuesPrevious,
                  })
                }
              />
            </Group>
            <Textarea
              label="Description"
              size="xs"
              autosize
              minRows={1}
              maxLength={300}
              value={shot.description}
              onChange={(event) =>
                change(index, { description: event.currentTarget.value })
              }
            />
            <MultiSelect
              label="Events shown"
              size="xs"
              data={eventOptions}
              value={shot.eventIds}
              onChange={(value) =>
                change(index, { eventIds: inStoryOrder(value, eventIds) })
              }
              searchable
            />
            <MultiSelect
              label="Speech heard"
              size="xs"
              data={unitOptions}
              value={shot.unitIds}
              onChange={(value) =>
                change(index, { unitIds: inStoryOrder(value, unitIds) })
              }
              searchable
            />
          </Stack>
        </Paper>
      ))}
      <Text size="xs" c="dimmed">
        Saving adds a new plan written by you. Every shot of this scene that
        was defined from the old plan will say it is out of date. The server
        checks the order of the events and speech, and the timeline is built
        again.
      </Text>
      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the shot plan"
        canSave={canSave}
        onSave={save}
        onCancel={onCancel}
      />
    </Stack>
  );
}
