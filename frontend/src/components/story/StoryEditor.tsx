import { useState } from "react";
import { Alert, Button, Group, Paper, Stack, Text, Textarea, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useUpdateProject, type ProjectDetail } from "../../api/projects";
import { countWords, estimateSeconds, formatDuration } from "./storyLength";

type DraftProps = {
  saved: string;
  wordsPerMinute: number;
  limitSeconds: number;
  isSaving: boolean;
  isSaved: boolean;
  error: string | null;
  onEdit: () => void;
  onSave: (text: string) => void;
};

/**
 * The draft lives here. The parent gives this component a key made from the saved story, so
 * the draft starts again from the saved text after a save.
 */
function StoryDraft({
  saved,
  wordsPerMinute,
  limitSeconds,
  isSaving,
  isSaved,
  error,
  onEdit,
  onSave,
}: DraftProps) {
  const [draft, setDraft] = useState(saved);
  const unchanged = draft === saved;

  const words = countWords(draft);
  const seconds = estimateSeconds(words, wordsPerMinute);
  const overLimit = seconds > limitSeconds;

  return (
    <Stack gap="sm">
      <Textarea
        aria-label="Story"
        placeholder="Paste the story here."
        value={draft}
        onChange={(event) => {
          setDraft(event.currentTarget.value);
          onEdit();
        }}
        autosize
        minRows={8}
        maxRows={30}
      />
      <Group justify="space-between">
        <Group gap="sm">
          <Button onClick={() => onSave(draft)} disabled={unchanged} loading={isSaving}>
            Save story
          </Button>
          {isSaved && unchanged && (
            <Text size="sm" c="green">
              Saved
            </Text>
          )}
        </Group>
        <Text size="xs" c="dimmed">
          {words} words · about {formatDuration(seconds)} at {wordsPerMinute} words per minute
        </Text>
      </Group>
      {overLimit && (
        <Alert color="yellow" title="This story is long">
          It is estimated at {formatDuration(seconds)}, above the limit of{" "}
          {formatDuration(limitSeconds)}. You can still save it, but the planning stages are
          designed for stories of about that length or shorter, so later stages may struggle. The
          limit and the pace are in Settings, under Story.
        </Alert>
      )}
      {error && !unchanged && (
        <Alert color="red" title="The story was not saved">
          {error}
        </Alert>
      )}
    </Stack>
  );
}

/** The project's story text: paste it, save it, and see its estimated length. */
export function StoryEditor({ project }: { project: ProjectDetail }) {
  const update = useUpdateProject(project.id);
  const saved = project.script_text ?? "";

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Title order={4}>Story</Title>
        <StoryDraft
          key={saved}
          saved={saved}
          wordsPerMinute={project.story_length.words_per_minute}
          limitSeconds={project.story_length.limit_seconds}
          isSaving={update.isPending}
          isSaved={update.isSuccess}
          error={update.isError ? describeError(update.error) : null}
          onEdit={update.reset}
          onSave={(text) => update.mutate({ script_text: text })}
        />
      </Stack>
    </Paper>
  );
}
