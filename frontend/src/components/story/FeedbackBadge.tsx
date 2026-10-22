import { Badge, Tooltip } from "@mantine/core";

type FeedbackBadgeProps = {
  /** The note the version was written with, or nothing for a version made without one. */
  text: string | null | undefined;
};

/**
 * Marks a version that the model wrote after reading the user's feedback. The note shows on
 * hover as plain text, so the user can see what the model was told.
 */
export function FeedbackBadge({ text }: FeedbackBadgeProps) {
  if (!text) {
    return null;
  }
  return (
    <Tooltip
      label={text}
      multiline
      w={320}
      withArrow
      style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}
    >
      <Badge
        variant="light"
        color="grape"
        style={{ cursor: "help", textTransform: "none" }}
      >
        Made with your feedback
      </Badge>
    </Tooltip>
  );
}
