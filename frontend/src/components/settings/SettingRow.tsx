import { useState } from "react";
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  HoverCard,
  NumberInput,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { useResetSetting, useSaveSetting, type SettingItem } from "../../api/settings";

function SourceBadge({ setting }: { setting: SettingItem }) {
  if (setting.source === "saved") {
    return (
      <Badge color="blue" size="sm">
        Saved
      </Badge>
    );
  }
  if (setting.source === "environment") {
    return (
      <Badge color="grape" size="sm">
        From {setting.env_var}
      </Badge>
    );
  }
  return (
    <Badge color="gray" size="sm">
      Default
    </Badge>
  );
}

function displayValue(setting: SettingItem): string {
  const { default: value, choices } = setting;
  if (value === "") return "(blank)";
  // A setting with a fixed set of values shows the name of the default, not its id.
  return choices?.find((choice) => choice.value === value)?.label ?? String(value);
}

/** The first sentence of a description: up to a full stop that is followed by a capital letter. */
function firstSentence(text: string): string {
  return text.split(/(?<=[.!?])\s+(?=[A-Z])/)[0] ?? text;
}

/** The mark that shows the full description of a setting while the pointer is over it. */
function InfoMark({ setting }: { setting: SettingItem }) {
  return (
    <HoverCard width={380} shadow="md" withArrow openDelay={100} position="bottom-start">
      <HoverCard.Target>
        <ActionIcon
          variant="default"
          size="xs"
          radius="xl"
          aria-label={`About ${setting.label}`}
          style={{ fontStyle: "italic", fontFamily: "serif" }}
        >
          i
        </ActionIcon>
      </HoverCard.Target>
      <HoverCard.Dropdown>
        <Stack gap="xs">
          <Text size="sm" fw={600}>
            {setting.label}
          </Text>
          <Text size="sm">{setting.help}</Text>
          <Text size="xs" c="dimmed">
            Default: {displayValue(setting)}
            {setting.env_var ? ` · Environment variable: ${setting.env_var}` : ""}
          </Text>
          {setting.will_call && (
            <Text size="xs">
              Will call: {setting.will_call}
              {setting.value === "" ? " (blank, so the remote server URL is used)" : ""}
            </Text>
          )}
        </Stack>
      </HoverCard.Dropdown>
    </HoverCard>
  );
}

/**
 * One setting with its own Save and Reset, so a validation error stays next to
 * its field. The page gives this component a key made from the saved state, so
 * the draft starts again from the new value after every save or reset.
 *
 * The row shows the name, a mark with the full description (and the default) while the pointer
 * is over it, and only the first sentence of the description under the field.
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

  return (
    <Stack gap={4}>
      <Group gap={6} wrap="nowrap" align="center">
        <Text size="sm" fw={600}>
          {label}
        </Text>
        <InfoMark setting={setting} />
        <SourceBadge setting={setting} />
      </Group>

      <Group align="flex-start" wrap="nowrap" gap="xs">
        {setting.value_type === "integer" ? (
          <NumberInput
            style={{ flex: 1 }}
            aria-label={label}
            value={draft}
            onChange={changeDraft}
            min={setting.min_value ?? undefined}
            max={setting.max_value ?? undefined}
            allowDecimal={false}
            allowNegative={false}
            clampBehavior="none"
            error={errorMessage}
          />
        ) : setting.choices ? (
          <Select
            style={{ flex: 1 }}
            aria-label={label}
            data={setting.choices.map((choice) => ({ value: choice.value, label: choice.label }))}
            value={String(draft)}
            onChange={(value) => value !== null && changeDraft(value)}
            allowDeselect={false}
            error={errorMessage}
          />
        ) : (
          <TextInput
            style={{ flex: 1 }}
            aria-label={label}
            value={String(draft)}
            onChange={(event) => changeDraft(event.currentTarget.value)}
            error={errorMessage}
          />
        )}
        <Group gap="xs" wrap="nowrap">
          <Button
            onClick={() => save.mutate({ key: setting.key, value: draft })}
            disabled={unchanged || reset.isPending}
            loading={save.isPending}
          >
            Save
          </Button>
          {setting.source === "saved" && (
            <Button
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

      <Text size="xs" c="dimmed">
        {firstSentence(setting.help)}
      </Text>

      {setting.note && (
        <Text size="xs" c="orange">
          {setting.note}
        </Text>
      )}
    </Stack>
  );
}
