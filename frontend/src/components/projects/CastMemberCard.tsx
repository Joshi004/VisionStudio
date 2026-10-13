import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  Image,
  Modal,
  Paper,
  Spoiler,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import {
  useEditCastMember,
  useGenerateReference,
  useWriteReferencePrompt,
  type CastMember,
  type CastMemberEdit,
} from "../../api/cast";
import { describeError } from "../../api/errors";
import { isJobActive } from "../../api/polling";
import type { ProjectDetail } from "../../api/projects";
import { JobActions } from "../jobs/JobActions";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { memberIsBusy, memberStatusColor, memberStatusText } from "./castView";

/** The backend's own limits. The server stays the judge; these only avoid a pointless save. */
const NAME_MAX_CHARS = 80;
const APPEARANCE_MAX_CHARS = 2000;
const NOTE_MAX_CHARS = 400;
const PROMPT_MAX_CHARS = 8000;

type CastMemberCardProps = {
  project: ProjectDetail;
  member: CastMember;
  /** The current time in milliseconds since 1970, for the job's elapsed time. */
  now: number;
};

/** The job to tell the user about: one that is running, or the newest one that failed. */
function shownJob(member: CastMember) {
  for (const job of [member.image_job, member.prompt_job]) {
    if (job !== null && (isJobActive(job) || job.status === "failed")) {
      return job;
    }
  }
  return null;
}

/**
 * One character or place: its picture, its description and its reference prompt, with Make
 * picture (the prompt is written first when there is none), Write prompt again and Edit. The
 * prompt is a paid call to the language model, and the picture is an image made on the GPU
 * server: each only starts from a click. Progress shows by itself.
 */
export function CastMemberCard({ project, member, now }: CastMemberCardProps) {
  const write = useWriteReferencePrompt(project.id);
  const generate = useGenerateReference(project.id);
  const [editing, setEditing] = useState(false);

  const busy = memberIsBusy(member);
  const hasPicture = member.reference_url !== null;
  const hasPrompt = member.reference_prompt !== null;
  const job = shownJob(member);
  const isCharacter = member.kind === "character";
  const noun = isCharacter ? "character" : "place";

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Stack gap={2}>
            <Text fw={600}>{member.name}</Text>
            <Text size="xs" c="dimmed">
              {member.scene_count === 0
                ? `No scene shows this ${noun} yet`
                : `Shown in ${member.scene_count} ${member.scene_count === 1 ? "scene" : "scenes"}`}
            </Text>
          </Stack>
          <Badge color={memberStatusColor(member)} variant="light">
            {memberStatusText(member)}
          </Badge>
        </Group>

        <Paper bg="gray.1" radius="sm" p={4}>
          {hasPicture ? (
            <Image
              src={member.reference_url}
              alt={`Reference picture of ${member.name}`}
              fit="contain"
              h={220}
            />
          ) : (
            <Text size="sm" c="dimmed" ta="center" py="xl">
              No picture yet
            </Text>
          )}
        </Paper>
        {hasPicture && (
          <Text size="xs" c="dimmed">
            {member.reference_width} x {member.reference_height}
            {isCharacter
              ? member.reference_has_transparency
                ? ", transparent backdrop"
                : ", on its white backdrop (the backdrop could not be removed)"
              : ""}
          </Text>
        )}

        <Text size="sm" lineClamp={4}>
          {member.appearance_description}
        </Text>
        {isCharacter && member.personality_description && (
          <Text size="xs" c="dimmed">
            Personality: {member.personality_description}
          </Text>
        )}
        {isCharacter && member.voice_description && (
          <Text size="xs" c="dimmed">
            Voice (a note for the AI; nobody speaks): {member.voice_description}
          </Text>
        )}
        {hasPrompt && (
          <Spoiler maxHeight={0} showLabel="Show the prompt" hideLabel="Hide the prompt">
            <Text size="xs" c="dimmed" style={{ whiteSpace: "pre-wrap" }}>
              {member.reference_prompt}
            </Text>
            <Text size="xs" c="dimmed" mt={4}>
              {member.reference_prompt_source === "manual" ? "Written by you." : "Written by the AI."}
            </Text>
          </Spoiler>
        )}

        <Group gap="xs">
          <Button
            size="compact-sm"
            disabled={busy}
            loading={generate.isPending}
            onClick={() => generate.mutate({ kind: member.kind, memberId: member.id })}
          >
            {hasPicture ? "Make the picture again" : "Make the picture"}
          </Button>
          {hasPrompt && (
            <Button
              size="compact-sm"
              variant="default"
              disabled={busy || member.prompt_blocked_reason !== null}
              loading={write.isPending}
              onClick={() =>
                write.mutate({ kind: member.kind, memberId: member.id, generateAfter: false })
              }
            >
              Write the prompt again
            </Button>
          )}
          <Button size="compact-sm" variant="subtle" onClick={() => setEditing(true)}>
            Edit
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          {hasPrompt
            ? "A picture takes a few minutes on your GPU server."
            : "Writes the prompt first (one paid call to the language model), then makes the picture on your GPU server."}
        </Text>

        {(generate.isError || write.isError) && (
          <Alert color="red" title="Not started">
            {describeError(generate.isError ? generate.error : write.error)}
          </Alert>
        )}

        {job !== null && (
          <Stack gap={4}>
            <Group gap="sm">
              <JobStatusBadge job={job} />
              <Text size="xs" c="dimmed">
                {job.type === "generate_character_reference" ? "Picture" : "Prompt"}:{" "}
                {elapsedText(job, now)}
              </Text>
              <JobActions job={job} />
            </Group>
            {job.status === "failed" && job.error && (
              <Text size="xs" c="red" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {job.error}
              </Text>
            )}
          </Stack>
        )}
      </Stack>

      {editing && <CastMemberEditor project={project} member={member} onClose={() => setEditing(false)} />}
    </Paper>
  );
}

type CastMemberEditorProps = {
  project: ProjectDetail;
  member: CastMember;
  onClose: () => void;
};

/**
 * The text of a character or place, in a window. It is mounted only while it is open, so its
 * boxes start from the saved text every time. Only what changed is sent. A prompt that is saved
 * becomes the user's own: an automatic run never replaces it.
 */
function CastMemberEditor({ project, member, onClose }: CastMemberEditorProps) {
  const save = useEditCastMember(project.id);
  const isCharacter = member.kind === "character";
  const [name, setName] = useState(member.name);
  const [appearance, setAppearance] = useState(member.appearance_description);
  const [personality, setPersonality] = useState(member.personality_description ?? "");
  const [voice, setVoice] = useState(member.voice_description ?? "");
  const [prompt, setPrompt] = useState(member.reference_prompt ?? "");

  const edit: CastMemberEdit = {};
  if (name !== member.name) {
    edit.name = name;
  }
  if (appearance !== member.appearance_description) {
    edit.appearance_description = appearance;
  }
  if (isCharacter && personality !== (member.personality_description ?? "")) {
    edit.personality_description = personality;
  }
  if (isCharacter && voice !== (member.voice_description ?? "")) {
    edit.voice_description = voice;
  }
  if (prompt !== (member.reference_prompt ?? "")) {
    edit.reference_prompt = prompt;
  }
  const changed = Object.keys(edit).length > 0;
  const invalid = name.trim() === "" || appearance.trim() === "";

  return (
    <Modal opened onClose={onClose} title={`Edit ${member.name}`} size="lg" centered>
      <Stack gap="sm">
        <TextInput
          label="Name"
          value={name}
          maxLength={NAME_MAX_CHARS}
          onChange={(event) => setName(event.currentTarget.value)}
          error={name.trim() === "" ? "The name cannot be blank." : undefined}
        />
        <Textarea
          label="What it looks like"
          description="The reference picture is made from this."
          value={appearance}
          maxLength={APPEARANCE_MAX_CHARS}
          onChange={(event) => setAppearance(event.currentTarget.value)}
          autosize
          minRows={4}
          maxRows={10}
          error={appearance.trim() === "" ? "The appearance cannot be blank." : undefined}
        />
        {isCharacter && (
          <>
            <Textarea
              label="Personality"
              description="Guides the bearing and the expression in the picture."
              value={personality}
              maxLength={NOTE_MAX_CHARS}
              onChange={(event) => setPersonality(event.currentTarget.value)}
              autosize
              minRows={2}
              maxRows={5}
            />
            <Textarea
              label="Voice"
              description="Only a note for the AI. Nobody speaks: a narrator tells the story."
              value={voice}
              maxLength={NOTE_MAX_CHARS}
              onChange={(event) => setVoice(event.currentTarget.value)}
              autosize
              minRows={2}
              maxRows={5}
            />
          </>
        )}
        <Textarea
          label="Reference prompt"
          description="What the image model is asked for. Leave it to the AI, or write your own: a prompt you write is never replaced by an automatic run."
          value={prompt}
          maxLength={PROMPT_MAX_CHARS}
          onChange={(event) => setPrompt(event.currentTarget.value)}
          autosize
          minRows={4}
          maxRows={14}
        />
        {save.isError && (
          <Alert color="red" title="Not saved">
            {describeError(save.error)}
          </Alert>
        )}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!changed || invalid}
            loading={save.isPending}
            onClick={() =>
              save.mutate({ kind: member.kind, memberId: member.id, edit }, { onSuccess: onClose })
            }
          >
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
