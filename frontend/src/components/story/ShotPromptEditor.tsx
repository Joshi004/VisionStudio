import { useState } from "react";
import type { ReactNode } from "react";
import { Stack, Text, Textarea } from "@mantine/core";

import type { ShotPromptContent } from "../../api/shotPrompts";
import { EditorActions } from "./editorParts";
import { PromptLegend } from "./PromptLegend";

type ShotPromptEditorProps = {
  /** The shot's newest prompt: its pieces are what is edited, its labels explain them. */
  prompt: ShotPromptContent;
  saving: boolean;
  error: unknown;
  onSave: (pieces: Record<string, string>) => void;
  /** More buttons after Save, given the edited pieces (for example "Save and generate"). */
  extra?: (pieces: Record<string, string>, canSave: boolean) => ReactNode;
  onCancel: () => void;
};

/** How each piece is shown. A piece not listed here is shown under its own name. */
const PIECE_LABEL: Record<string, string> = {
  style: "Style",
  summary: "Summary",
  shot: "Shot",
  soundscape: "Soundscape",
  integrated_multimodal_description: "Description",
  overall_soundscape: "Soundscape",
};

const SUBJECT_PREFIX = "subject_";

/** The pieces in the order the prompt reads: style, the subjects, summary, shot, soundscape. */
function orderedKeys(pieces: Record<string, string>): string[] {
  const keys = Object.keys(pieces);
  const subjects = keys
    .filter((key) => key.startsWith(SUBJECT_PREFIX))
    .sort(
      (a, b) =>
        Number(a.slice(SUBJECT_PREFIX.length)) -
        Number(b.slice(SUBJECT_PREFIX.length)),
    );
  const known = [
    "style",
    ...subjects,
    "summary",
    "shot",
    "soundscape",
    "integrated_multimodal_description",
    "overall_soundscape",
  ].filter((key) => keys.includes(key));
  // Anything else is kept, after the known ones, so that no piece is lost on save.
  return [...known, ...keys.filter((key) => !known.includes(key))];
}

function pieceLabel(key: string): string {
  if (key.startsWith(SUBJECT_PREFIX)) {
    return `Subject ${key.slice(SUBJECT_PREFIX.length)}`;
  }
  return PIECE_LABEL[key] ?? key;
}

/**
 * One shot's prompt, edited by hand. Only the pieces the model writes are shown (the style, each
 * subject, the summary, the shot and the soundscape): code writes the headings, the labels, the
 * lines that say how each picture and speech is used and the music line, and builds the prompt
 * again from the pieces when it is saved. The server refuses a prompt that loses a spoken
 * line (its exact words, its audio label or its start time) or that is longer than the video
 * model takes.
 */
export function ShotPromptEditor({
  prompt,
  saving,
  error,
  onSave,
  extra,
  onCancel,
}: ShotPromptEditorProps) {
  const [pieces, setPieces] = useState<Record<string, string>>({
    ...prompt.pieces,
  });
  const canSave = Object.values(pieces).every((text) => text.trim() !== "");
  const trimmed = () =>
    Object.fromEntries(
      Object.entries(pieces).map(([key, text]) => [key, text.trim()]),
    );

  return (
    <Stack gap="sm">
      <PromptLegend prompt={prompt} />
      {orderedKeys(pieces).map((key) => (
        <Textarea
          key={key}
          label={pieceLabel(key)}
          autosize
          minRows={2}
          value={pieces[key]}
          onChange={(event) =>
            setPieces({ ...pieces, [key]: event.currentTarget.value })
          }
        />
      ))}
      <Text size="xs" c="dimmed">
        Spoken lines stay in the shot with their exact words, audio label and
        start time. Saving adds a new prompt written by you; the video model
        gets it exactly as it is built from these pieces.
      </Text>
      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the shot prompt"
        canSave={canSave}
        extra={extra?.(trimmed(), canSave)}
        onSave={() => onSave(trimmed())}
        onCancel={onCancel}
      />
    </Stack>
  );
}
