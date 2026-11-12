import { useState } from "react";
import { Alert, Avatar, Badge, Button, Group, Loader, Paper, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useCheckYouTubeChannel,
  useStartYouTubeSignIn,
  useYouTubeChannels,
  useYouTubeConfig,
  type YouTubeChannel,
} from "../../api/youtube";
import { DisconnectYouTubeChannelModal } from "./DisconnectYouTubeChannelModal";

/** What the sign-in came back with (`?youtube=` on the Settings address), in words. */
const SIGN_IN_RESULTS: Record<string, { color: string; text: string }> = {
  connected: { color: "green", text: "The channel is connected." },
  denied: {
    color: "orange",
    text: "Access was denied at Google, so nothing was connected. Press Connect to try again.",
  },
  expired: {
    color: "orange",
    text: "That sign-in has expired or was already used. Press Connect to start again.",
  },
  no_channel: {
    color: "red",
    text: "That Google account has no YouTube channel to connect. Create the channel on YouTube, or choose another account.",
  },
  missing_scope: {
    color: "red",
    text: "Google did not give the app permission to manage your YouTube videos. Connect again and allow every permission it asks for.",
  },
  no_refresh_token: {
    color: "red",
    text: "Google did not give a lasting sign-in. Remove this app at myaccount.google.com under Security, Third-party access, then connect again.",
  },
  not_configured: {
    color: "red",
    text: "YouTube is not set up in .env, so nothing was connected.",
  },
  failed: {
    color: "red",
    text: "The sign-in failed. Press Connect to try again. If it keeps failing, check the backend log.",
  },
};

type YouTubeChannelsSectionProps = {
  /** The result code from the address, when the browser has just come back from Google. */
  signInResult: string | null;
  onDismissSignInResult: () => void;
};

function ChannelRow({
  channel,
  connectDisabled,
  onDisconnect,
}: {
  channel: YouTubeChannel;
  connectDisabled: boolean;
  onDisconnect: () => void;
}) {
  const check = useCheckYouTubeChannel();
  const startSignIn = useStartYouTubeSignIn();
  const needsReconnect = channel.status === "needs_reconnect";

  return (
    <Stack gap="xs">
      <Group justify="space-between" align="center" wrap="wrap">
        <Group gap="sm" wrap="nowrap">
          <Avatar src={channel.thumbnail_url} alt="" radius="xl" />
          <Stack gap={0}>
            <Text fw={500}>{channel.title}</Text>
            <Text size="xs" c="dimmed">
              {channel.channel_id}
              {channel.last_used_at
                ? ` · last used ${new Date(channel.last_used_at).toLocaleString()}`
                : ""}
            </Text>
          </Stack>
          <Badge color={needsReconnect ? "orange" : "green"}>
            {needsReconnect ? "Needs reconnecting" : "Connected"}
          </Badge>
        </Group>
        <Group gap="xs">
          <Button
            variant="default"
            size="xs"
            onClick={() => check.mutate(channel.id)}
            loading={check.isPending}
          >
            Check
          </Button>
          <Button
            variant={needsReconnect ? "filled" : "default"}
            size="xs"
            onClick={() => startSignIn.mutate()}
            loading={startSignIn.isPending}
            disabled={connectDisabled}
          >
            Reconnect
          </Button>
          <Button variant="default" color="red" size="xs" onClick={onDisconnect}>
            Disconnect
          </Button>
        </Group>
      </Group>
      {check.isError && (
        <Text c="red" size="sm">
          Could not check the channel: {describeError(check.error)}
        </Text>
      )}
      {check.isSuccess && check.data.status === "connected" && (
        <Text c="green" size="sm">
          Google accepted the sign-in.
        </Text>
      )}
      {check.isSuccess && check.data.status === "needs_reconnect" && (
        <Text c="orange" size="sm">
          Google no longer accepts this sign-in. Press Reconnect and choose this channel again.
        </Text>
      )}
      {startSignIn.isError && (
        <Text c="red" size="sm">
          {describeError(startSignIn.error)}
        </Text>
      )}
    </Stack>
  );
}

export function YouTubeChannelsSection({
  signInResult,
  onDismissSignInResult,
}: YouTubeChannelsSectionProps) {
  const config = useYouTubeConfig();
  const channels = useYouTubeChannels();
  const startSignIn = useStartYouTubeSignIn();
  const [disconnecting, setDisconnecting] = useState<YouTubeChannel | null>(null);

  const ready = config.data?.ready === true;
  const result = signInResult ? SIGN_IN_RESULTS[signInResult] : undefined;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Text fw={600}>YouTube channels</Text>
            <Text size="sm" c="dimmed">
              Connect each channel you publish to once. Open the app at the same address as the
              redirect address in .env when you connect. While the Google app is in Testing, a
              connection stops working after 7 days: press Reconnect then.
            </Text>
          </Stack>
          <Button
            onClick={() => startSignIn.mutate()}
            loading={startSignIn.isPending}
            disabled={!ready}
          >
            Connect a channel
          </Button>
        </Group>

        {result && (
          <Alert color={result.color} withCloseButton onClose={onDismissSignInResult}>
            {result.text}
          </Alert>
        )}

        {config.isLoading && <Loader size="sm" />}
        {config.isError && (
          <Text c="red" size="sm">
            {describeError(config.error)}
          </Text>
        )}
        {config.data && !config.data.ready && (
          <Alert color="orange" title="YouTube is not set up in .env yet">
            <Stack gap={4}>
              {config.data.missing.map((name) => (
                <Text size="sm" key={name}>
                  {name} is missing.
                </Text>
              ))}
              {config.data.invalid.map((problem) => (
                <Text size="sm" key={problem.name}>
                  {problem.name} is not valid. {problem.reason}
                </Text>
              ))}
              <Text size="sm">
                Fix .env, then restart the backend (docker compose up -d). The values are never
                shown here.
              </Text>
            </Stack>
          </Alert>
        )}

        {startSignIn.isError && (
          <Text c="red" size="sm">
            {describeError(startSignIn.error)}
          </Text>
        )}

        {channels.isLoading && <Loader size="sm" />}
        {channels.isError && (
          <Text c="red" size="sm">
            {describeError(channels.error)}
          </Text>
        )}
        {channels.data?.length === 0 && (
          <Text size="sm" c="dimmed">
            No channel is connected yet.
          </Text>
        )}
        {channels.data?.map((channel) => (
          <ChannelRow
            key={channel.id}
            channel={channel}
            connectDisabled={!ready}
            onDisconnect={() => setDisconnecting(channel)}
          />
        ))}
      </Stack>

      {disconnecting && (
        <DisconnectYouTubeChannelModal
          channel={disconnecting}
          onClose={() => setDisconnecting(null)}
        />
      )}
    </Paper>
  );
}
