import { useState } from "react";
import { Alert, Button, Group, Modal, Stack, Text, Textarea } from "@mantine/core";

/** The longest note the server accepts. */
const FEEDBACK_MAX_CHARS = 2000;

type FeedbackFormProps = {
  /** What the model is asked to rewrite, for example "the prompt of this shot". */
  what: string;
  /** The note the newest version was made with, so the user can add to it. */
  initialText: string;
  /** True when the newest version was written by the user. */
  writtenByUser: boolean;
  submitLabel: string;
  onCancel: () => void;
  onSubmit: (text: string) => void;
};

/** Rebuilt every time the modal opens, so the field always starts from `initialText`. */
function FeedbackForm({
  what,
  initialText,
  writtenByUser,
  submitLabel,
  onCancel,
  onSubmit,
}: FeedbackFormProps) {
  const [text, setText] = useState(initialText);
  const note = text.trim();

  return (
    <Stack gap="md">
      <Text size="sm">
        Write what is wrong or what you want different. The model reads your note together
        with the version you see now, and writes {what} again. The fixed instructions of the
        step and every check stay as they are, so the new version still has to follow them.
      </Text>
      {writtenByUser && (
        <Alert color="yellow" p="xs" title="Your own version is newest">
          The newest version was written by you. The model&apos;s new version is added on top of
          it, and yours stays in the list of versions.
        </Alert>
      )}
      <Textarea
        label="Your feedback"
        description="Plain text. It is used once, for this rewrite."
        autosize
        minRows={4}
        maxRows={12}
        maxLength={FEEDBACK_MAX_CHARS}
        value={text}
        onChange={(event) => setText(event.currentTarget.value)}
        data-autofocus
      />
      <Text size="xs" c="dimmed" ta="right">
        {text.length} of {FEEDBACK_MAX_CHARS}
      </Text>
      <Group justify="flex-end">
        <Button variant="default" onClick={onCancel}>
          Cancel
        </Button>
        <Button disabled={note === ""} onClick={() => onSubmit(note)}>
          {submitLabel}
        </Button>
      </Group>
    </Stack>
  );
}

type FeedbackModalProps = FeedbackFormProps & {
  opened: boolean;
  title: string;
};

/**
 * Asks the user for a note on the newest version of something the model wrote. The note is
 * given to the model once, next to the version it is about. Nothing is sent from here: the
 * caller starts the job in `onSubmit`.
 */
export function FeedbackModal({ opened, title, ...form }: FeedbackModalProps) {
  return (
    <Modal opened={opened} onClose={form.onCancel} title={title} centered size="lg">
      <FeedbackForm {...form} />
    </Modal>
  );
}
