import { Alert, Badge, Group, Loader, Paper, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../api/errors";
import { useSettings, type SettingItem } from "../api/settings";
import { ContractSection } from "../components/settings/ContractSection";
import { GpuConnectionTest } from "../components/settings/GpuConnectionTest";
import { SettingRow } from "../components/settings/SettingRow";

/** Groups settings by their `group`, keeping the order the backend sent them in. */
function groupSettings(settings: SettingItem[]): [string, SettingItem[]][] {
  const groups = new Map<string, SettingItem[]>();
  for (const setting of settings) {
    const members = groups.get(setting.group) ?? [];
    members.push(setting);
    groups.set(setting.group, members);
  }
  return [...groups.entries()];
}

export function SettingsPage() {
  const { data, isLoading, isError, error } = useSettings();

  return (
    <Stack gap="lg" maw={760}>
      <Title order={2}>Settings</Title>

      {isLoading && <Loader size="sm" />}

      {isError && (
        <Alert color="red" title="Could not load the settings">
          {describeError(error)} Press Refresh to try again.
        </Alert>
      )}

      {data && (
        <>
          <GpuConnectionTest />
          <ContractSection />

          {groupSettings(data.settings).map(([group, settings]) => (
            <Stack key={group} gap="md">
              <Title order={4}>{group}</Title>
              <Paper withBorder p="md" radius="md">
                <Stack gap="lg">
                  {settings.map((setting) => (
                    <SettingRow
                      key={`${setting.key}|${setting.source}|${setting.value}`}
                      setting={setting}
                    />
                  ))}
                </Stack>
              </Paper>
            </Stack>
          ))}

          <Stack gap="md">
            <Title order={4}>Secrets</Title>
            <Paper withBorder p="md" radius="md">
              <Stack gap="md">
                {data.secrets.map((secret) => (
                  <Group key={secret.name} justify="space-between">
                    <Stack gap={2}>
                      <Text fw={500}>{secret.label}</Text>
                      <Text size="xs" c="dimmed">
                        {secret.name} is read from .env and is never shown.
                      </Text>
                    </Stack>
                    <Badge color={secret.is_set ? "green" : "red"}>
                      Key set: {secret.is_set ? "yes" : "no"}
                    </Badge>
                  </Group>
                ))}
              </Stack>
            </Paper>
          </Stack>
        </>
      )}
    </Stack>
  );
}
