import { Alert, Button, Group, Stack, Text, TextInput } from "@mantine/core";

import { describeError } from "../../api/errors";

type StringListInputProps = {
  label: string;
  hint?: string;
  values: string[];
  addLabel: string;
  onChange: (values: string[]) => void;
};

/** A list of short texts: one input per entry, with Add and Remove. */
export function StringListInput({ label, hint, values, addLabel, onChange }: StringListInputProps) {
  return (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        {label}
      </Text>
      {hint && (
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      )}
      {values.map((value, index) => (
        <Group key={index} gap="xs" wrap="nowrap">
          <TextInput
            aria-label={`${label} ${index + 1}`}
            value={value}
            onChange={(event) => {
              const text = event.currentTarget.value;
              onChange(values.map((item, position) => (position === index ? text : item)));
            }}
            style={{ flex: 1 }}
          />
          <Button
            variant="default"
            aria-label={`Remove ${label} ${index + 1}`}
            onClick={() => onChange(values.filter((_, position) => position !== index))}
          >
            Remove
          </Button>
        </Group>
      ))}
      <Group>
        <Button variant="default" size="xs" onClick={() => onChange([...values, ""])}>
          {addLabel}
        </Button>
      </Group>
    </Stack>
  );
}

type EditorActionsProps = {
  saving: boolean;
  /** The error of the last save, shown above the buttons. */
  error: unknown;
  /** The title of that error, for example "Could not save the Story Bible". */
  errorTitle: string;
  canSave?: boolean;
  onSave: () => void;
  onCancel: () => void;
};

/** The server's reason a save was refused, then Save and Cancel. */
export function EditorActions({
  saving,
  error,
  errorTitle,
  canSave = true,
  onSave,
  onCancel,
}: EditorActionsProps) {
  return (
    <Stack gap="xs">
      {error !== null && error !== undefined && (
        <Alert color="red" title={errorTitle}>
          {describeError(error)}
        </Alert>
      )}
      <Group>
        <Button onClick={onSave} loading={saving} disabled={!canSave}>
          Save
        </Button>
        <Button variant="default" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </Group>
    </Stack>
  );
}
