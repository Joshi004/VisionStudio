import { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import { useSearchParams } from "react-router";

import { describeError } from "../api/errors";
import { useSettings, type SettingItem } from "../api/settings";
import { ContractSection } from "../components/settings/ContractSection";
import { GpuConnectionTest } from "../components/settings/GpuConnectionTest";
import { SettingRow } from "../components/settings/SettingRow";
import { YouTubeChannelsSection } from "../components/settings/YouTubeChannelsSection";

/** The group (tab) that also holds the connection test and the API contract. */
const GPU_GROUP = "Remote server";
/** The group (tab) that also holds the connected YouTube channels. */
const YOUTUBE_GROUP = "YouTube";
const SECRETS_TAB = "Secrets";

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
  const [searchParams, setSearchParams] = useSearchParams();
  // Google sends the browser back with `?youtube=<result>`. Keep the result, open the YouTube tab
  // and take the parameter out of the address so a reload does not show it again.
  const [signInResult, setSignInResult] = useState<string | null>(() =>
    searchParams.get("youtube"),
  );
  const [chosenTab, setChosenTab] = useState<string | null>(() =>
    searchParams.has("youtube") ? YOUTUBE_GROUP : null,
  );
  useEffect(() => {
    if (searchParams.has("youtube")) {
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const groups = data ? groupSettings(data.settings) : [];
  // Until a tab is chosen, the first group is shown.
  const activeTab = chosenTab ?? groups[0]?.[0] ?? SECRETS_TAB;

  return (
    <Stack gap="lg" maw={1000}>
      <Title order={2}>Settings</Title>

      {isLoading && <Loader size="sm" />}

      {isError && (
        <Alert color="red" title="Could not load the settings">
          {describeError(error)} Press Refresh to try again.
        </Alert>
      )}

      {data && (
        <Tabs value={activeTab} onChange={setChosenTab} keepMounted={false}>
          <Tabs.List style={{ flexWrap: "wrap" }}>
            {groups.map(([group, settings]) => {
              const savedCount = settings.filter((setting) => setting.source === "saved").length;
              return (
                <Tabs.Tab
                  key={group}
                  value={group}
                  rightSection={
                    savedCount > 0 ? (
                      <Badge size="xs" circle color="blue" title={`${savedCount} saved`}>
                        {savedCount}
                      </Badge>
                    ) : undefined
                  }
                >
                  {group}
                </Tabs.Tab>
              );
            })}
            <Tabs.Tab value={SECRETS_TAB}>{SECRETS_TAB}</Tabs.Tab>
          </Tabs.List>

          {groups.map(([group, settings]) => (
            <Tabs.Panel key={group} value={group} pt="md">
              <Stack gap="lg">
                {group === GPU_GROUP && (
                  <>
                    <GpuConnectionTest />
                    <ContractSection />
                  </>
                )}
                {group === YOUTUBE_GROUP && (
                  <YouTubeChannelsSection
                    signInResult={signInResult}
                    onDismissSignInResult={() => setSignInResult(null)}
                  />
                )}
                <Paper withBorder p="md" radius="md">
                  <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg" verticalSpacing="lg">
                    {settings.map((setting) => (
                      <SettingRow
                        key={`${setting.key}|${setting.source}|${setting.value}`}
                        setting={setting}
                      />
                    ))}
                  </SimpleGrid>
                </Paper>
              </Stack>
            </Tabs.Panel>
          ))}

          <Tabs.Panel value={SECRETS_TAB} pt="md">
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
          </Tabs.Panel>
        </Tabs>
      )}
    </Stack>
  );
}
