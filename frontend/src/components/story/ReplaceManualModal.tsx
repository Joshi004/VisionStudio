import { Button, Group, Modal, Stack, Text } from "@mantine/core";

type ReplaceManualModalProps = {
  opened: boolean;
  /** The question, for example "Find the relations again?". */
  title: string;
  /** What is about to be replaced, for example "The newest relations". */
  what: string;
  /** The button that goes ahead, for example "Find again". */
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
};

/**
 * Asks before the model writes over something the user wrote. Nothing is lost: the model's
 * result is added as a new version, and the user's version stays in the list of versions.
 */
export function ReplaceManualModal({
  opened,
  title,
  what,
  confirmLabel,
  onCancel,
  onConfirm,
}: ReplaceManualModalProps) {
  return (
    <Modal opened={opened} onClose={onCancel} title={title} centered>
      <Stack gap="md">
        <Text size="sm">
          {what} was written by you. Running the model again adds a new version from the model on
          top. Your version stays in the list of versions.
        </Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button color="red" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
