import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Group,
  List,
  Stack,
  TagsInput,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import type { YouTubeDraft } from "../../api/youtube";
import {
  DESCRIPTION_MAX_BYTES,
  HASHTAGS_MAX,
  TITLE_MAX_CHARS,
  descriptionBytes,
  draftProblems,
  normalizedDescription,
  normalizedHashtag,
  normalizedTitle,
  titleLength,
} from "./youtubeLimits";

export type YouTubeDraftEdit = {
  title: string;
  description: string;
  hashtags: string[];
};

type YouTubeDraftEditorProps = {
  draft: YouTubeDraft;
  /** True while the draft is being written: nothing can be changed. */
  busy: boolean;
  saving: boolean;
  saveError: unknown;
  onSave: (edit: YouTubeDraftEdit) => void;
  /** Tells the panel whether there are edits that are not saved yet. */
  onDirtyChange: (dirty: boolean) => void;
};

/**
 * The title, the description and the hashtags of a draft, with YouTube's limits shown as the
 * owner types. Saving adds a version written by the owner; a draft that breaks a limit cannot be
 * saved. The panel remounts it with the draft's version as the key, so a new version starts clean.
 */
export function YouTubeDraftEditor({
  draft,
  busy,
  saving,
  saveError,
  onSave,
  onDirtyChange,
}: YouTubeDraftEditorProps) {
  const [title, setTitle] = useState(draft.title);
  const [description, setDescription] = useState(draft.description);
  const [hashtags, setHashtags] = useState<string[]>(draft.hashtags);

  const changed =
    normalizedTitle(title) !== draft.title ||
    normalizedDescription(description) !== draft.description ||
    hashtags.join(" ") !== draft.hashtags.join(" ");
  useEffect(() => {
    onDirtyChange(changed);
  }, [changed, onDirtyChange]);

  const problems = draftProblems({ title, description, hashtags });
  const titleChars = titleLength(title);
  const bytes = descriptionBytes(description, hashtags);

  const undo = () => {
    setTitle(draft.title);
    setDescription(draft.description);
    setHashtags(draft.hashtags);
  };

  return (
    <Stack gap="sm">
      <TextInput
        label="Title"
        description={`${titleChars} of ${TITLE_MAX_CHARS} characters`}
        value={title}
        disabled={busy}
        error={titleChars > TITLE_MAX_CHARS || /[<>]/.test(title)}
        onChange={(event) => setTitle(event.currentTarget.value)}
      />
      <Textarea
        label="Description"
        description={`${bytes.toLocaleString()} of ${DESCRIPTION_MAX_BYTES.toLocaleString()} bytes, counting the hashtags`}
        autosize
        minRows={4}
        maxRows={14}
        value={description}
        disabled={busy}
        error={bytes > DESCRIPTION_MAX_BYTES || /[<>]/.test(description)}
        onChange={(event) => setDescription(event.currentTarget.value)}
      />
      <TagsInput
        label="Hashtags"
        description={`Up to ${HASHTAGS_MAX}, one word each. Type one and press Enter; the # is added when the video is sent.`}
        value={hashtags}
        splitChars={[",", " "]}
        disabled={busy}
        onChange={(values) =>
          setHashtags(values.map(normalizedHashtag).filter((tag) => tag !== ""))
        }
      />
      {changed && problems.length > 0 && (
        <Alert color="red" title="This cannot be saved yet">
          <List size="sm">
            {problems.map((problem) => (
              <List.Item key={problem}>{problem}</List.Item>
            ))}
          </List>
        </Alert>
      )}
      {saveError !== null && saveError !== undefined && (
        <Alert color="red" title="Could not save the draft">
          {describeError(saveError)}
        </Alert>
      )}
      <Group>
        <Button
          onClick={() => onSave({ title, description, hashtags })}
          loading={saving}
          disabled={busy || !changed || problems.length > 0}
        >
          Save edits
        </Button>
        {changed && (
          <Button variant="subtle" color="gray" onClick={undo} disabled={saving}>
            Undo changes
          </Button>
        )}
        {!changed && (
          <Text size="xs" c="dimmed">
            Saving adds a version written by you.
          </Text>
        )}
      </Group>
    </Stack>
  );
}
