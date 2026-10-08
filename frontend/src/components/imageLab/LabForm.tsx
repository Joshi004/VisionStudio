import { Button, Group, Select, SegmentedControl, Stack, Text, TextInput, Textarea } from "@mantine/core";

import type { LabMode } from "../../api/imageLab";
import {
  blockedReason,
  costText,
  MODE_LABELS,
  MODE_NOTES,
  parseExtra,
  SIZE_PRESETS,
  type LabFormState,
  type ReferenceItem,
} from "./labView";
import { ReferenceTray } from "./ReferenceTray";

type LabFormProps = {
  state: LabFormState;
  onChange: (update: (current: LabFormState) => LabFormState) => void;
  onRun: () => void;
  running: boolean;
};

/**
 * The form of one test. Every field is sent as it is: a setting the API ignores is still sent,
 * so the result shows whether it did anything. "Not sent" leaves a setting out, to see the
 * API's own default.
 */
export function LabForm({ state, onChange, onRun, running }: LabFormProps) {
  function set<K extends keyof LabFormState>(key: K, value: LabFormState[K]) {
    onChange((current) => ({ ...current, [key]: value }));
  }

  const extra = parseExtra(state.extraJson);
  const blocked = blockedReason(state);
  const usesReferences = state.mode !== "text_to_image";

  return (
    <Stack gap="md">
      <Stack gap={4}>
        <SegmentedControl
          value={state.mode}
          onChange={(value) => set("mode", value as LabMode)}
          data={(Object.keys(MODE_LABELS) as LabMode[]).map((mode) => ({
            value: mode,
            label: MODE_LABELS[mode],
          }))}
          disabled={running}
        />
        <Text size="xs" c="dimmed">
          {MODE_NOTES[state.mode]}
        </Text>
      </Stack>

      <Textarea
        label="Prompt"
        description="In image to image and edit modes, refer to the references as image 1, image 2 and so on, in the order shown below."
        value={state.prompt}
        onChange={(event) => set("prompt", event.currentTarget.value)}
        autosize
        minRows={4}
        maxRows={14}
        disabled={running}
      />

      <Group align="flex-start" grow>
        <TextInput
          label="Model"
          value={state.model}
          onChange={(event) => set("model", event.currentTarget.value)}
          disabled={running}
        />
        <Select
          label="Size"
          data={SIZE_PRESETS}
          value={state.sizePreset}
          onChange={(value) => set("sizePreset", value ?? "1632x2880")}
          allowDeselect={false}
          disabled={running}
        />
        {state.sizePreset === "custom" && (
          <TextInput
            label="Custom size"
            placeholder="1632x2880 or 2K"
            value={state.customSize}
            onChange={(event) => set("customSize", event.currentTarget.value)}
            disabled={running}
          />
        )}
      </Group>

      <Group align="flex-start" grow>
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Watermark
          </Text>
          <SegmentedControl
            value={state.watermark}
            onChange={(value) => set("watermark", value as LabFormState["watermark"])}
            data={[
              { value: "off", label: "Off" },
              { value: "on", label: "On" },
              { value: "unset", label: "Not sent" },
            ]}
            disabled={running}
          />
        </Stack>
        <TextInput
          label="Seed"
          description="Empty: not sent."
          placeholder="42"
          inputMode="numeric"
          value={state.seed}
          onChange={(event) => set("seed", event.currentTarget.value)}
          disabled={running}
        />
        <TextInput
          label="Image set, at most"
          description="Empty: one image. A number asks for a set."
          placeholder="2"
          inputMode="numeric"
          value={state.setMax}
          onChange={(event) => set("setMax", event.currentTarget.value)}
          disabled={running}
        />
      </Group>

      {state.mode === "image_to_image" && (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            How the image field is sent
          </Text>
          <SegmentedControl
            value={state.imageFieldAs}
            onChange={(value) => set("imageFieldAs", value as "list" | "string")}
            data={[
              { value: "list", label: "A list" },
              { value: "string", label: "A single string (one reference)" },
            ]}
            disabled={running}
          />
        </Stack>
      )}
      {state.mode === "edit" && (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Name of the file field
          </Text>
          <SegmentedControl
            value={state.editFieldName}
            onChange={(value) => set("editFieldName", value as "image" | "image[]")}
            data={[
              { value: "image", label: "image" },
              { value: "image[]", label: "image[]" },
            ]}
            disabled={running}
          />
        </Stack>
      )}

      <ReferenceTray
        items={state.references}
        onChange={(update: (current: ReferenceItem[]) => ReferenceItem[]) =>
          onChange((current) => ({ ...current, references: update(current.references) }))
        }
        mode={state.mode}
      />

      <Textarea
        label="Extra JSON"
        description='Any other parameter, as a JSON object, for example {"guidance_scale": 7.5}. It is added to the request, and may override the settings above (not model, prompt or image).'
        placeholder="{}"
        value={state.extraJson}
        onChange={(event) => set("extraJson", event.currentTarget.value)}
        error={extra.error ?? undefined}
        autosize
        minRows={2}
        maxRows={10}
        styles={{ input: { fontFamily: "var(--mantine-font-family-monospace)" } }}
        disabled={running}
      />

      <Group gap="sm" align="center">
        <Button onClick={onRun} disabled={blocked !== null} loading={running} size="md">
          Run ({costText(state)})
        </Button>
        {running ? (
          <Text size="sm" c="dimmed">
            Running, usually 25 to 40 s. Keep this page open. If you leave, the run still finishes
            and appears in the history.
          </Text>
        ) : (
          <Text size="sm" c="dimmed">
            {blocked ?? (usesReferences ? "Sends the prompt and the references." : "Sends the prompt.")}
          </Text>
        )}
      </Group>
      <Text size="xs" c="dimmed">
        A paid call: Bitdeer charges per generated image (about $0.035). Nothing is retried, and the
        same request is never reused from an earlier run.
      </Text>
    </Stack>
  );
}
