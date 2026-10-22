import { Stack, Text } from "@mantine/core";

import type {
  PromptSpeaker,
  PromptSubject,
  ShotPromptContent,
} from "../../api/shotPrompts";

function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

/** What a subject is, in a few words: its name and the views of it that are sent. */
function subjectText(subject: PromptSubject): string {
  const views = subject.views.map((view) => humanize(view)).join(", ");
  const what = subject.kind === "environment" ? "the place" : subject.subject_name;
  return `${what} (${subject.subject_id}): ${views}`;
}

function speakerText(speaker: PromptSpeaker): string {
  const who = speaker.visible
    ? `says it (${speaker.subject_label ?? speaker.speaker_id})`
    : "unseen speaker";
  return `${speaker.speaker_id}, ${speaker.speaker}, ${who}, starts at ${speaker.cue}: \u201c${speaker.text}\u201d`;
}

/** What the labels of a prompt stand for, so that a reader can follow the text. */
export function PromptLegend({ prompt }: { prompt: ShotPromptContent }) {
  return (
    <Stack gap={2}>
      {prompt.subjects.map((subject) => (
        <Text key={subject.label} size="xs" c="dimmed">
          &lt;{subject.label}&gt; {subjectText(subject)}; shown in{" "}
          {subject.pictures.map((label) => `<${label}>`).join(", ")}
        </Text>
      ))}
      {prompt.speakers.map((speaker) => (
        <Text key={speaker.audio_label} size="xs" c="dimmed">
          &lt;{speaker.audio_label}&gt; {speakerText(speaker)}
        </Text>
      ))}
    </Stack>
  );
}
