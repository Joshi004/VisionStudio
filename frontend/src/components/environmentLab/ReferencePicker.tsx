import {
  Accordion,
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";

import {
  useChooseReference,
  useEnvironmentReferences,
  useStartReference,
  type EnvironmentReference,
  type LibraryEnvironment,
  type ReferenceCandidate,
} from "../../api/environmentLab";
import { describeError } from "../../api/errors";
import { formatDateTime } from "../../format";
import { JobStatusBadge } from "../jobs/JobStatusBadge";

const PICTURE_STYLE = {
  width: "100%",
  aspectRatio: "16 / 9",
  objectFit: "cover",
  background: "var(--mantine-color-gray-1)",
  borderRadius: 4,
  display: "block",
} as const;

const PLACEHOLDER_STYLE = {
  ...PICTURE_STYLE,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  flexDirection: "column",
  gap: 6,
} as const;

function CandidateTile({
  candidate,
  position,
  frozen,
  onChoose,
  choosing,
}: {
  candidate: ReferenceCandidate;
  position: number;
  /** The attempt was made for an older version: it is shown, but cannot be chosen from. */
  frozen: boolean;
  onChoose: () => void;
  choosing: boolean;
}) {
  const job = candidate.job;
  const failed = job !== null && (job.status === "failed" || job.status === "cancelled");
  return (
    <Stack gap={6}>
      {candidate.url !== null ? (
        <img
          src={candidate.url}
          alt={`Candidate ${position}`}
          loading="lazy"
          style={{
            ...PICTURE_STYLE,
            outline: candidate.chosen ? "3px solid var(--mantine-color-blue-6)" : "none",
          }}
        />
      ) : (
        <div style={PLACEHOLDER_STYLE}>
          {job !== null && !failed ? <Loader size="sm" /> : null}
          {job !== null && <JobStatusBadge job={job} />}
        </div>
      )}
      {failed && job?.error && (
        <Text size="xs" c="red" lineClamp={3} title={job.error}>
          {job.error}
        </Text>
      )}
      {candidate.chosen ? (
        <Badge variant="filled" color="blue">
          Canonical
        </Badge>
      ) : (
        <Button
          size="compact-sm"
          variant={frozen ? "default" : "filled"}
          disabled={candidate.url === null || frozen}
          loading={choosing}
          onClick={onChoose}
        >
          Use this one
        </Button>
      )}
    </Stack>
  );
}

function AttemptView({
  attempt,
  chooseFor,
  choosingCandidateId,
}: {
  attempt: EnvironmentReference;
  chooseFor: (candidateId: number) => void;
  choosingCandidateId: number | null;
}) {
  return (
    <Stack gap="sm">
      {attempt.status === "writing_prompt" && (
        <Group gap="sm">
          <Loader size="sm" />
          <Text size="sm">Writing the prompt...</Text>
          {attempt.prompt_job !== null && <JobStatusBadge job={attempt.prompt_job} />}
        </Group>
      )}
      {attempt.status === "failed" && (
        <Alert color="red" title="This picture could not be made">
          {attempt.error ?? "No reason was given."}
        </Alert>
      )}
      {attempt.status === "ready" && (
        <Stack gap="sm">
          {attempt.frozen ? (
            <Text size="xs" c="dimmed">
              Made for version {attempt.version}, which is frozen: a newer version exists, so this
              choice cannot be changed.
            </Text>
          ) : (
            <Text size="sm" fw={500}>
              Choose the one you like. It becomes the picture of version {attempt.version}.
            </Text>
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            {attempt.candidates.map((candidate, index) => (
              <CandidateTile
                key={candidate.id}
                candidate={candidate}
                position={index + 1}
                frozen={attempt.frozen}
                choosing={choosingCandidateId === candidate.id}
                onChoose={() => chooseFor(candidate.id)}
              />
            ))}
          </SimpleGrid>
          {!attempt.frozen && (
            <Text size="xs" c="dimmed">
              The pictures take a few minutes. This page updates by itself.
            </Text>
          )}
        </Stack>
      )}
      {attempt.prompt !== null && (
        <Text size="xs" c="dimmed" lineClamp={3} title={attempt.prompt}>
          Prompt: {attempt.prompt}
        </Text>
      )}
    </Stack>
  );
}

/**
 * Making the picture of an environment's newest version: a model writes the prompt, four wide
 * pictures are drawn, and the one you choose becomes the version's canonical picture. Earlier
 * attempts are listed below, and are read-only once a newer version exists.
 */
export function ReferencePicker({ environment }: { environment: LibraryEnvironment }) {
  const references = useEnvironmentReferences(environment.id);
  const start = useStartReference();
  const choose = useChooseReference();
  const attempts = references.data ?? [];
  const [newest, ...earlier] = attempts;
  const writingPrompt = attempts.some((attempt) => attempt.status === "writing_prompt" && !attempt.frozen);
  const choosingCandidateId = choose.isPending ? (choose.variables?.candidateId ?? null) : null;

  function chooseFor(attempt: EnvironmentReference, candidateId: number) {
    choose.mutate({ referenceId: attempt.id, candidateId });
  }

  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Text size="sm" fw={600}>
          Reference picture
        </Text>
        <Button
          size="compact-sm"
          loading={start.isPending}
          disabled={environment.archived || writingPrompt}
          onClick={() => start.mutate(environment.id)}
        >
          {environment.image === null ? "Make the picture" : "Make a new picture"}
        </Button>
      </Group>
      <Text size="xs" c="dimmed">
        For version {environment.version ?? "?"}. A wide, empty view of the place, with four to
        choose from.
      </Text>

      {environment.archived && (
        <Alert color="orange" p="xs">
          This environment is archived. Unarchive it to make a picture.
        </Alert>
      )}
      {start.isError && (
        <Alert color="red" p="xs" title="The picture could not be started">
          {describeError(start.error)}
        </Alert>
      )}
      {choose.isError && (
        <Alert color="red" p="xs" title="The picture was not chosen">
          {describeError(choose.error)}
        </Alert>
      )}
      {references.isLoading && <Loader size="xs" />}
      {references.isError && (
        <Alert color="red" p="xs" title="Could not load the pictures">
          {describeError(references.error)}
        </Alert>
      )}
      {references.data && attempts.length === 0 && (
        <Text size="xs" c="dimmed">
          No picture has been made yet.
        </Text>
      )}

      {newest !== undefined && (
        <Paper withBorder p="sm" radius="md">
          <AttemptView
            attempt={newest}
            chooseFor={(candidateId) => chooseFor(newest, candidateId)}
            choosingCandidateId={choosingCandidateId}
          />
        </Paper>
      )}

      {earlier.length > 0 && (
        <Stack gap="xs">
          <Text size="sm" fw={500}>
            Earlier attempts
          </Text>
          <Accordion variant="contained">
            {earlier.map((attempt) => (
              <Accordion.Item key={attempt.id} value={String(attempt.id)}>
                <Accordion.Control>
                  <Group gap="xs">
                    <Text size="sm" fw={500}>
                      Version {attempt.version}
                    </Text>
                    <Badge
                      variant="light"
                      color={attempt.status === "failed" ? "red" : "gray"}
                      size="sm"
                    >
                      {attempt.status === "ready"
                        ? "pictures"
                        : attempt.status === "failed"
                          ? "failed"
                          : "writing the prompt"}
                    </Badge>
                    <Text size="xs" c="dimmed">
                      {formatDateTime(attempt.created_at)}
                    </Text>
                  </Group>
                </Accordion.Control>
                <Accordion.Panel>
                  <AttemptView
                    attempt={attempt}
                    chooseFor={(candidateId) => chooseFor(attempt, candidateId)}
                    choosingCandidateId={choosingCandidateId}
                  />
                </Accordion.Panel>
              </Accordion.Item>
            ))}
          </Accordion>
        </Stack>
      )}
    </Stack>
  );
}
