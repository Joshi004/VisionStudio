import { useState } from "react";
import { Alert, Button, Group, Paper, Stack, Text, Textarea, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useUpdateProject, type ProjectDetail } from "../../api/projects";

function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

/** Paragraphs are blocks of text separated by at least one blank line. */
function countParagraphs(text: string): number {
  return text.split(/\r?\n[ \t]*\r?\n/).filter((block) => block.trim() !== "").length;
}

type ScriptEditorProps = {
  saved: string;
  isSaving: boolean;
  isSaved: boolean;
  error: string | null;
  onEdit: () => void;
  onSave: (text: string) => void;
};

/**
 * The draft lives here. The parent gives this component a key made from the
 * saved script, so the draft starts again from the saved text after a save.
 */
function ScriptEditor({ saved, isSaving, isSaved, error, onEdit, onSave }: ScriptEditorProps) {
  const [draft, setDraft] = useState(saved);
  const unchanged = draft === saved;

  return (
    <Stack gap="sm">
      <Textarea
        aria-label="Script"
        placeholder="Paste the script here."
        description="Blank lines between paragraphs are scene-break hints."
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
            Save script
          </Button>
          {isSaved && unchanged && (
            <Text size="sm" c="green">
              Saved
            </Text>
          )}
        </Group>
        <Text size="xs" c="dimmed">
          {countWords(draft)} words · {countParagraphs(draft)} paragraphs
        </Text>
      </Group>
      {error && !unchanged && (
        <Alert color="red" title="The script was not saved">
          {error}
        </Alert>
      )}
    </Stack>
  );
}

export function ScriptSection({ project }: { project: ProjectDetail }) {
  const update = useUpdateProject(project.id);
  const saved = project.script_text ?? "";

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Title order={4}>Script</Title>
        <ScriptEditor
          key={saved}
          saved={saved}
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
