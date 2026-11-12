import { Alert, Button, Group, Modal, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useDisconnectYouTubeChannel, type YouTubeChannel } from "../../api/youtube";

type DisconnectYouTubeChannelModalProps = {
  channel: YouTubeChannel;
  onClose: () => void;
};

/**
 * Asks before a channel is disconnected. The app tries to revoke the channel's token at Google
 * and removes the channel either way; when Google could not be told, the dialog says so and
 * points to the page where access can be removed by hand.
 */
export function DisconnectYouTubeChannelModal({
  channel,
  onClose,
}: DisconnectYouTubeChannelModalProps) {
  const disconnect = useDisconnectYouTubeChannel();
  const notRevoked = disconnect.data?.revoked === false;

  function confirm() {
    disconnect.mutate(channel.id, {
      onSuccess: (result) => {
        // Nothing more to say when Google was told: close at once.
        if (result.revoked) {
          onClose();
        }
      },
    });
  }

  return (
    <Modal opened onClose={onClose} title={`Disconnect ${channel.title}?`} centered>
      <Stack gap="md">
        {!disconnect.isSuccess && (
          <Text size="sm">
            The app forgets this channel and asks Google to cancel its access. Videos already on
            YouTube are not touched. Past uploads stay in each project&apos;s list. To publish to
            this channel again you connect it again.
          </Text>
        )}

        {notRevoked && (
          <Alert color="orange" title="The channel was disconnected, but Google was not told">
            Google could not be reached, so its access may still be listed. You can remove it at
            myaccount.google.com, under Security, Third-party access.
          </Alert>
        )}

        {disconnect.isError && (
          <Alert color="red" title="It was not disconnected">
            {describeError(disconnect.error)}
          </Alert>
        )}

        <Group justify="flex-end">
          {disconnect.isSuccess ? (
            <Button onClick={onClose}>Close</Button>
          ) : (
            <>
              <Button variant="default" onClick={onClose} disabled={disconnect.isPending}>
                Cancel
              </Button>
              <Button color="red" onClick={confirm} loading={disconnect.isPending}>
                Disconnect
              </Button>
            </>
          )}
        </Group>
      </Stack>
    </Modal>
  );
}
