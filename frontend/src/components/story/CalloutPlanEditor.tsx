import { useState } from "react";
import { Button, Group, Paper, Select, Stack, Switch, Text, TextInput } from "@mantine/core";

import type {
  Callout,
  CalloutEdit,
  CalloutPlanInput,
  CalloutRole,
  CalloutScriptLine,
  CalloutType,
} from "../../api/calloutPlan";
import { EditorActions } from "./editorParts";
import {
  ITEM_MAX_CHARS,
  MAX_ITEMS,
  MIN_ITEMS,
  ROLE_OPTIONS,
  SIDE_MAX_CHARS,
  TEXT_MAX_CHARS,
  TYPE_OPTIONS,
  formatClock,
} from "./calloutPlanView";

type ItemDraft = { text: string; phrase: string | null };
type SideDraft = { text: string; phrase: string | null; role: CalloutRole };
type Draft = {
  id: string;
  type: CalloutType;
  role: CalloutRole;
  enabled: boolean;
  text: string;
  items: ItemDraft[];
  sides: SideDraft[];
  // Not editable: where the callout sits.
  phrase: string;
  sceneId: string;
  unitId: string;
  startS: number;
};

type CalloutPlanEditorProps = {
  /** The newest plan's callouts; the form starts from them. */
  initial: Callout[];
  script: CalloutScriptLine[];
  saving: boolean;
  error: unknown;
  onSave: (content: CalloutPlanInput) => void;
  onCancel: () => void;
};

type TextType = keyof typeof TEXT_MAX_CHARS;

function isTextType(type: CalloutType): type is TextType {
  return type in TEXT_MAX_CHARS;
}

function defaultRole(type: CalloutType): CalloutRole {
  return type === "number" ? "number" : "accent";
}

function toDraft(callout: Callout): Draft {
  return {
    id: callout.id,
    type: callout.type,
    role: callout.role ?? defaultRole(callout.type),
    enabled: callout.enabled,
    text: callout.text ?? "",
    items: (callout.items ?? []).map((item) => ({ text: item.text, phrase: item.phrase })),
    sides: (callout.sides ?? []).map((side) => ({
      text: side.text,
      phrase: side.phrase,
      role: side.role,
    })),
    phrase: callout.phrase,
    sceneId: callout.scene_id,
    unitId: callout.unit_id,
    startS: callout.estimated_start_s,
  };
}

/** Every text the callout holds, so a change of type does not lose what was written. */
function textsOf(draft: Draft): string[] {
  return [draft.text, ...draft.items.map((item) => item.text), ...draft.sides.map((s) => s.text)]
    .map((text) => text.trim())
    .filter((text) => text !== "");
}

/** The draft as another type: the same texts, laid out as that type needs them. */
function withType(draft: Draft, type: CalloutType): Draft {
  if (type === draft.type) return draft;
  const texts = textsOf(draft);
  const next: Draft = { ...draft, type, role: defaultRole(type) };
  if (isTextType(type)) {
    next.text = texts[0] ?? "";
  } else if (type === "list") {
    const items = draft.items.length >= MIN_ITEMS ? draft.items : [];
    next.items =
      items.length > 0
        ? items
        : Array.from({ length: MIN_ITEMS }, (_, index) => ({
            text: texts[index] ?? "",
            phrase: null,
          }));
  } else {
    next.sides =
      draft.sides.length === 2
        ? draft.sides
        : [
            { text: texts[0] ?? "", phrase: null, role: "negative" },
            { text: texts[1] ?? "", phrase: null, role: "positive" },
          ];
  }
  return next;
}

function toEdit(draft: Draft): CalloutEdit {
  return {
    id: draft.id,
    type: draft.type,
    enabled: draft.enabled,
    role: draft.type === "comparison" ? null : draft.role,
    text: isTextType(draft.type) ? draft.text.trim() : null,
    items:
      draft.type === "list"
        ? draft.items.map((item) => ({ text: item.text.trim(), phrase: item.phrase }))
        : null,
    sides:
      draft.type === "comparison"
        ? draft.sides.map((side) => ({
            text: side.text.trim(),
            phrase: side.phrase,
            role: side.role,
          }))
        : null,
  };
}

/**
 * The callouts as a form: each one can be turned on or off, and its type, role and text can be
 * changed. Callouts cannot be added or removed, and where each one sits is not edited here. The
 * server checks the result by the same display rules as the model's answer and says which
 * callout is wrong.
 */
export function CalloutPlanEditor({
  initial,
  script,
  saving,
  error,
  onSave,
  onCancel,
}: CalloutPlanEditorProps) {
  const [drafts, setDrafts] = useState<Draft[]>(() => initial.map(toDraft));

  const lineOf = (draft: Draft) =>
    script.find((line) => line.scene_id === draft.sceneId && line.unit_id === draft.unitId);

  const update = (id: string, change: (draft: Draft) => Draft) =>
    setDrafts((current) => current.map((draft) => (draft.id === id ? change(draft) : draft)));

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Turn a callout off to keep it out of the video, or change its words, type and colour. You
        cannot add or remove callouts here: run the plan again for that.
      </Text>
      {drafts.map((draft, index) => {
        const line = lineOf(draft);
        return (
          <Paper key={draft.id} withBorder p="sm" radius="md">
            <Stack gap="xs">
              <Group justify="space-between" align="flex-end" wrap="wrap">
                <Group gap="sm" align="flex-end">
                  <Switch
                    aria-label={`Callout ${index + 1} on`}
                    label={`Callout ${index + 1}`}
                    checked={draft.enabled}
                    onChange={(event) => {
                      const enabled = event.currentTarget.checked;
                      update(draft.id, (current) => ({ ...current, enabled }));
                    }}
                  />
                  <Select
                    aria-label={`Type of callout ${index + 1}`}
                    w={160}
                    allowDeselect={false}
                    data={TYPE_OPTIONS}
                    value={draft.type}
                    onChange={(value) =>
                      value !== null &&
                      update(draft.id, (current) => withType(current, value as CalloutType))
                    }
                  />
                  {draft.type !== "comparison" && (
                    <Select
                      aria-label={`Colour of callout ${index + 1}`}
                      w={170}
                      allowDeselect={false}
                      data={ROLE_OPTIONS}
                      value={draft.role}
                      onChange={(value) =>
                        value !== null &&
                        update(draft.id, (current) => ({
                          ...current,
                          role: value as CalloutRole,
                        }))
                      }
                    />
                  )}
                </Group>
                <Text size="xs" c="dimmed">
                  About {formatClock(draft.startS)}
                  {line ? ` · ${line.scene_title}` : ""}
                </Text>
              </Group>

              {isTextType(draft.type) && (
                <TextInput
                  aria-label={`Text of callout ${index + 1}`}
                  value={draft.text}
                  maxLength={TEXT_MAX_CHARS[draft.type]}
                  description={`${draft.text.length} / ${TEXT_MAX_CHARS[draft.type]}`}
                  onChange={(event) => {
                    const text = event.currentTarget.value;
                    update(draft.id, (current) => ({ ...current, text }));
                  }}
                />
              )}

              {draft.type === "list" && (
                <Stack gap={4}>
                  {draft.items.map((item, itemIndex) => (
                    <Group key={itemIndex} gap="xs" wrap="nowrap">
                      <TextInput
                        aria-label={`Item ${itemIndex + 1} of callout ${index + 1}`}
                        value={item.text}
                        maxLength={ITEM_MAX_CHARS}
                        style={{ flex: 1 }}
                        onChange={(event) => {
                          const text = event.currentTarget.value;
                          update(draft.id, (current) => ({
                            ...current,
                            items: current.items.map((entry, position) =>
                              position === itemIndex ? { ...entry, text } : entry,
                            ),
                          }));
                        }}
                      />
                      <Button
                        variant="default"
                        aria-label={`Remove item ${itemIndex + 1} of callout ${index + 1}`}
                        disabled={draft.items.length <= MIN_ITEMS}
                        onClick={() =>
                          update(draft.id, (current) => ({
                            ...current,
                            items: current.items.filter((_, position) => position !== itemIndex),
                          }))
                        }
                      >
                        Remove
                      </Button>
                    </Group>
                  ))}
                  <Group>
                    <Button
                      variant="default"
                      size="xs"
                      disabled={draft.items.length >= MAX_ITEMS}
                      onClick={() =>
                        update(draft.id, (current) => ({
                          ...current,
                          items: [...current.items, { text: "", phrase: null }],
                        }))
                      }
                    >
                      Add item
                    </Button>
                  </Group>
                </Stack>
              )}

              {draft.type === "comparison" && (
                <Stack gap={4}>
                  {draft.sides.map((side, sideIndex) => (
                    <Group key={sideIndex} gap="xs" wrap="nowrap" align="flex-end">
                      <TextInput
                        aria-label={`Side ${sideIndex + 1} of callout ${index + 1}`}
                        value={side.text}
                        maxLength={SIDE_MAX_CHARS}
                        style={{ flex: 1 }}
                        onChange={(event) => {
                          const text = event.currentTarget.value;
                          update(draft.id, (current) => ({
                            ...current,
                            sides: current.sides.map((entry, position) =>
                              position === sideIndex ? { ...entry, text } : entry,
                            ),
                          }));
                        }}
                      />
                      <Select
                        aria-label={`Colour of side ${sideIndex + 1} of callout ${index + 1}`}
                        w={170}
                        allowDeselect={false}
                        data={ROLE_OPTIONS}
                        value={side.role}
                        onChange={(value) =>
                          value !== null &&
                          update(draft.id, (current) => ({
                            ...current,
                            sides: current.sides.map((entry, position) =>
                              position === sideIndex
                                ? { ...entry, role: value as CalloutRole }
                                : entry,
                            ),
                          }))
                        }
                      />
                    </Group>
                  ))}
                </Stack>
              )}

              <Text size="xs" c="dimmed">
                Sits on: “{draft.phrase}”
              </Text>
            </Stack>
          </Paper>
        );
      })}
      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the callouts"
        onSave={() => onSave({ callouts: drafts.map(toEdit) })}
        onCancel={onCancel}
      />
    </Stack>
  );
}
