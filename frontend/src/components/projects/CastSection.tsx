import { useState } from "react";
import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { castHasActiveJob, useAssignCast, useCast, useExtractCast, type Cast } from "../../api/cast";
import { describeError } from "../../api/errors";
import type { ProjectDetail } from "../../api/projects";
import { useNow } from "../../hooks/useNow";
import { useRefreshWhenFinished } from "../../hooks/useRefreshWhenFinished";
import { JobActions } from "../jobs/JobActions";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { CastMemberCard } from "./CastMemberCard";
import { assignedLine, pictureCountsLine } from "./castView";

type CastJob = Cast["extract_job"];

/** A job's status line, with its error when it failed. Nothing when there was no job. */
function JobLine({ label, job, now }: { label: string; job: CastJob; now: number }) {
  if (job === null) {
    return null;
  }
  return (
    <Stack gap={2}>
      <Group gap="sm">
        <Text size="xs" c="dimmed">
          {label}
        </Text>
        <JobStatusBadge job={job} />
        <Text size="xs" c="dimmed">
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
  );
}

/**
 * The project's cast: the characters and the places of the story, each with one reference
 * picture, so every scene that shows one looks the same. Find characters and places (a paid call
 * to the language model that reads the script) and Choose who is in each scene (another) only
 * start from a click, with a confirmation. A scene shows any characters and at most one place:
 * its first frame is made from their pictures. Progress shows by itself.
 */
export function CastSection({ project }: { project: ProjectDetail }) {
  const query = useCast(project.id);
  const extract = useExtractCast(project.id);
  const assign = useAssignCast(project.id);
  const [confirming, setConfirming] = useState<"extract" | "assign" | null>(null);

  const cast = query.data;
  const active = castHasActiveJob(cast);
  const now = useNow(active, query.dataUpdatedAt);
  useRefreshWhenFinished(active);

  function startExtract() {
    if (cast !== undefined) {
      extract.mutate({ confirmReplace: cast.extract_needs_confirmation });
    }
    setConfirming(null);
  }

  function startAssign() {
    assign.mutate();
    setConfirming(null);
  }

  const empty = cast !== undefined && cast.characters.length === 0 && cast.locations.length === 0;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Title order={4}>Characters and places</Title>
        <Text size="sm" c="dimmed">
          Each character and place of the story gets one reference picture, so every scene that
          shows it looks the same. A scene shows any characters and at most one place, and its
          first frame is made from their pictures. Nobody speaks: a narrator tells the story.
        </Text>

        {query.isLoading && <Loader size="sm" />}
        {query.isError && (
          <Alert color="red" title="Could not load the cast">
            {describeError(query.error)}
          </Alert>
        )}

        {cast !== undefined && (
          <>
            <Group gap="sm" align="center">
              <Button
                size="xs"
                disabled={cast.extract_blocked_reason !== null || active}
                loading={extract.isPending}
                onClick={() => setConfirming("extract")}
              >
                {empty ? "Find characters and places" : "Find them again"}
              </Button>
              <Button
                size="xs"
                variant="default"
                disabled={cast.assign_blocked_reason !== null || active}
                loading={assign.isPending}
                onClick={() => setConfirming("assign")}
              >
                Choose who is in each scene
              </Button>
            </Group>
            {cast.extract_blocked_reason !== null && (
              <Text size="xs" c="dimmed">
                {cast.extract_blocked_reason}
              </Text>
            )}
            {cast.assign_blocked_reason !== null && !empty && (
              <Text size="xs" c="dimmed">
                {cast.assign_blocked_reason}
              </Text>
            )}

            {(extract.isError || assign.isError) && (
              <Alert color="red" title="Not started">
                {describeError(extract.isError ? extract.error : assign.error)}
              </Alert>
            )}
            {cast.script_changed && (
              <Alert color="yellow" title="The script changed">
                This cast was found in an earlier script. Find the characters and places again to
                update it. That replaces all of them and their pictures.
              </Alert>
            )}

            <JobLine label="Finding the cast:" job={cast.extract_job} now={now} />
            <JobLine label="Choosing who is in each scene:" job={cast.assign_job} now={now} />

            {empty ? (
              <Text size="sm" c="dimmed">
                No characters or places yet.
              </Text>
            ) : (
              <>
                <Text size="xs" c="dimmed">
                  {pictureCountsLine(cast)}. {assignedLine(cast)}
                  {active ? " This updates by itself." : ""}
                </Text>
                {cast.characters.length > 0 && (
                  <Stack gap="xs">
                    <Title order={5}>Characters</Title>
                    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                      {cast.characters.map((member) => (
                        <CastMemberCard
                          key={member.id}
                          project={project}
                          member={member}
                          now={now}
                        />
                      ))}
                    </SimpleGrid>
                  </Stack>
                )}
                {cast.locations.length > 0 && (
                  <Stack gap="xs">
                    <Title order={5}>Places</Title>
                    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                      {cast.locations.map((member) => (
                        <CastMemberCard
                          key={member.id}
                          project={project}
                          member={member}
                          now={now}
                        />
                      ))}
                    </SimpleGrid>
                  </Stack>
                )}
              </>
            )}
          </>
        )}
      </Stack>

      <Modal
        opened={confirming === "extract"}
        onClose={() => setConfirming(null)}
        title="Before the language model is called"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Reads the whole script and lists its characters and places, each with a description of
            how it looks: one paid call to the language model.
          </Text>
          {cast?.extract_needs_confirmation && (
            <Alert color="yellow" title="This replaces the cast">
              <Text size="sm">
                Every character and place, their reference pictures and the choice of who is in
                each scene are replaced. The picture files stay on disk, but belong to nobody.
              </Text>
            </Alert>
          )}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
            <Button onClick={startExtract}>Continue</Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={confirming === "assign"}
        onClose={() => setConfirming(null)}
        title="Before the language model is called"
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            Chooses, for every scene, the characters and the one place it shows, from the cast
            above: one paid call that sends the narration of every scene and the cast. A choice you
            made yourself is kept.
          </Text>
          <Text size="sm">
            A scene whose choice changes needs its image prompt written again.
          </Text>
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
            <Button onClick={startAssign}>Continue</Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
}
