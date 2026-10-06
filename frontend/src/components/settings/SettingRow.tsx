import { useState } from "react";
import { Badge, Button, Group, NumberInput, Stack, Text, TextInput } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useResetSetting, useSaveSetting, type SettingItem } from "../../api/settings";

function SourceBadge({ setting }: { setting: SettingItem }) {
  if (setting.source === "saved") {
    return <Badge color="blue">Saved</Badge>;
  }
  if (setting.source === "environment") {
    return <Badge color="grape">From {setting.env_var}</Badge>;
  }
  return <Badge color="gray">Built-in default</Badge>;
}

function displayValue(value: string | number): string {
  return value === "" ? "(blank)" : String(value);
}

/**
 * One setting with its own Save and Reset, so a validation error stays next to
 * its field. The page gives this component a key made from the saved state, so
 * the draft starts again from the new value after every save or reset.
 */
export function SettingRow({ setting }: { setting: SettingItem }) {
  const [draft, setDraft] = useState<string | number>(setting.value);
  const save = useSaveSetting();
  const reset = useResetSetting();

  const unchanged = draft === setting.value;
  const errorMessage = save.isError
    ? describeError(save.error)
    : reset.isError
      ? describeError(reset.error)
      : undefined;

  function changeDraft(value: string | number) {
    setDraft(value);
    save.reset();
    reset.reset();
  }

  const label = setting.label;
  const description = setting.help;

  return (
    <Stack gap={6}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        {setting.value_type === "integer" ? (
          <NumberInput
            style={{ flex: 1 }}
            label={label}
            description={description}
            value={draft}
            onChange={changeDraft}
            min={setting.min_value ?? undefined}
            max={setting.max_value ?? undefined}
            allowDecimal={false}
            allowNegative={false}
            clampBehavior="none"
            error={errorMessage}
          />
        ) : (
          <TextInput
            style={{ flex: 1 }}
            label={label}
            description={description}
            value={String(draft)}
            onChange={(event) => changeDraft(event.currentTarget.value)}
            error={errorMessage}
          />
        )}
        <Group gap="xs" mt={22} wrap="nowrap">
          <Button
            size="sm"
            onClick={() => save.mutate({ key: setting.key, value: draft })}
            disabled={unchanged || reset.isPending}
            loading={save.isPending}
          >
            Save
          </Button>
          {setting.source === "saved" && (
            <Button
              size="sm"
              variant="default"
              onClick={() => reset.mutate(setting.key)}
              disabled={save.isPending}
              loading={reset.isPending}
            >
              Reset
            </Button>
          )}
        </Group>
      </Group>

      <Group gap="xs">
        <SourceBadge setting={setting} />
        <Text size="xs" c="dimmed">
          Default: {displayValue(setting.default)}
          {setting.env_var ? ` · Environment variable: ${setting.env_var}` : ""}
        </Text>
      </Group>

      {setting.will_call && (
        <Text size="xs">
          Will call: {setting.will_call}
          {setting.value === "" ? " (blank, so the GPU server URL is used)" : ""}
        </Text>
      )}
      {setting.note && (
        <Text size="xs" c="orange">
          {setting.note}
        </Text>
      )}
    </Stack>
  );
}
