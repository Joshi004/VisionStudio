import { useEffect, useState } from "react";
import { Alert, Button, Group, Paper, Stack, Tabs, Text, Textarea, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useUpdateProject, type ProjectDetail } from "../../api/projects";
import { StoryMarkup } from "./StoryMarkup";
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
  /** Told whether the draft differs from the saved story, whenever that changes. */
  onUnsavedChange: (unsaved: boolean) => void;
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
  onUnsavedChange,
}: DraftProps) {
  const [draft, setDraft] = useState(saved);
  const unchanged = draft === saved;

  useEffect(() => {
    onUnsavedChange(!unchanged);
  }, [unchanged, onUnsavedChange]);

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

/**
 * The project's story text. Write: paste it, save it, and see its estimated length. Mark up:
 * select words of the saved story and mark them as evidence, a graphic, or both.
 */
export function StoryEditor({ project }: { project: ProjectDetail }) {
  const update = useUpdateProject(project.id);
  const saved = project.script_text ?? "";
  const [hasUnsavedStory, setHasUnsavedStory] = useState(false);
  // How many suggested graphics the last save could no longer find in the changed story.
  const [droppedSuggestions, setDroppedSuggestions] = useState(0);
  // Only a continuous explainer with graphics or evidence on has words to mark.
  const marksUp =
    project.voice_track === "continuous" && (project.graphics || project.evidence);
  // A saved story opens on Mark up; a new project starts on Write.
  const [tab, setTab] = useState<string>(project.script_text !== null && marksUp ? "markup" : "write");

  function save(text: string) {
    const before = project.graphic_suggestions.length;
    update.mutate(
      { script_text: text },
      {
        onSuccess: (updated) =>
          setDroppedSuggestions(Math.max(0, before - updated.graphic_suggestions.length)),
      },
    );
  }

  const draft = (
    <StoryDraft
      key={saved}
      saved={saved}
      wordsPerMinute={project.story_length.words_per_minute}
      limitSeconds={project.story_length.limit_seconds}
      isSaving={update.isPending}
      isSaved={update.isSuccess}
      error={update.isError ? describeError(update.error) : null}
      onEdit={() => {
        update.reset();
        setDroppedSuggestions(0);
      }}
      onSave={save}
      onUnsavedChange={setHasUnsavedStory}
    />
  );

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Title order={4}>Story</Title>
        {marksUp ? (
          // Both panels stay mounted, so a draft is not lost when the reader switches tabs.
          <Tabs value={tab} onChange={(value) => setTab(value ?? "write")} keepMounted>
            <Tabs.List mb="sm">
              <Tabs.Tab value="write">Write</Tabs.Tab>
              <Tabs.Tab value="markup">Mark up</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="write">{draft}</Tabs.Panel>
            <Tabs.Panel value="markup">
              <StoryMarkup
                project={project}
                hasUnsavedStory={hasUnsavedStory}
                onGoToWrite={() => setTab("write")}
              />
            </Tabs.Panel>
          </Tabs>
        ) : (
          draft
        )}
        {droppedSuggestions > 0 && (
          <Alert color="yellow" title="Some graphic suggestions were removed">
            {droppedSuggestions === 1
              ? "1 graphic suggestion"
              : `${droppedSuggestions} graphic suggestions`}{" "}
            no longer matched the changed story and were removed.
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}
