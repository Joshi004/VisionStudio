import { useState } from "react";
import { Stack, Text, TextInput, Textarea } from "@mantine/core";

import type { StoryBibleInput } from "../../api/storyBible";
import { EditorActions, StringListInput } from "./editorParts";

type StoryBibleEditorProps = {
  /** The newest Story Bible; the form starts from it. */
  initial: StoryBibleInput;
  saving: boolean;
  error: unknown;
  onSave: (content: StoryBibleInput) => void;
  onCancel: () => void;
};

/**
 * The Story Bible as a form. The language is not here: it is the story's and is set by code.
 * The server checks the sizes and says which field is wrong.
 */
export function StoryBibleEditor({
  initial,
  saving,
  error,
  onSave,
  onCancel,
}: StoryBibleEditorProps) {
  // Only the fields that can be written: the stored content also has the language, and the
  // server refuses a field it does not know.
  const [draft, setDraft] = useState<StoryBibleInput>({
    title: initial.title,
    genre: [...initial.genre],
    tone: [...initial.tone],
    visual_style: initial.visual_style,
    time_period: initial.time_period,
    storytelling_style: { narration: initial.storytelling_style.narration },
    world_rules: [...initial.world_rules],
  });
  const change = (part: Partial<StoryBibleInput>) => setDraft({ ...draft, ...part });

  return (
    <Stack gap="sm">
      <TextInput
        label="Title"
        value={draft.title}
        onChange={(event) => change({ title: event.currentTarget.value })}
      />
      <StringListInput
        label="Genre"
        hint="One to four, most important first."
        values={draft.genre}
        addLabel="Add a genre"
        onChange={(genre) => change({ genre })}
      />
      <StringListInput
        label="Tone"
        hint="Words or short phrases for the mood and how it develops."
        values={draft.tone}
        addLabel="Add a tone"
        onChange={(tone) => change({ tone })}
      />
      <Textarea
        label="Visual style"
        autosize
        minRows={2}
        value={draft.visual_style}
        onChange={(event) => change({ visual_style: event.currentTarget.value })}
      />
      <TextInput
        label="Time period"
        value={draft.time_period}
        onChange={(event) => change({ time_period: event.currentTarget.value })}
      />
      <Textarea
        label="Narration style"
        autosize
        minRows={2}
        value={draft.storytelling_style.narration}
        onChange={(event) => change({ storytelling_style: { narration: event.currentTarget.value } })}
      />
      <StringListInput
        label="World rules"
        hint="Up to ten rules the story's world follows. None is fine."
        values={draft.world_rules}
        addLabel="Add a rule"
        onChange={(world_rules) => change({ world_rules })}
      />
      <Text size="xs" c="dimmed">
        Saving adds a new version written by you. The stages after it will say they are out of
        date.
      </Text>
      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the Story Bible"
        onSave={() => onSave(draft)}
        onCancel={onCancel}
      />
    </Stack>
  );
}
