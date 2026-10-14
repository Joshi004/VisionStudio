import { Alert, Badge, Button, Group, Loader, Paper, SimpleGrid, Stack, Text } from "@mantine/core";

import {
  lookIsBusy,
  useChooseMaster,
  useCharacterLooks,
  useRedoAngle,
  useStartLook,
  type Angle,
  type CharacterLook,
  type LibraryCharacter,
  type LookCandidate,
} from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ANGLE_LABELS, ANGLES, referencePicture } from "./characterLabView";

const PICTURE_STYLE = {
  width: "100%",
  aspectRatio: "2 / 3",
  objectFit: "contain",
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
  onChoose,
  choosing,
}: {
  candidate: LookCandidate;
  position: number;
  onChoose: () => void;
  choosing: boolean;
}) {
  const job = candidate.job;
  const failed = job !== null && (job.status === "failed" || job.status === "cancelled");
  return (
    <Stack gap={6}>
      {candidate.url !== null ? (
        <img src={candidate.url} alt={`Candidate ${position}`} loading="lazy" style={PICTURE_STYLE} />
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
      <Button size="compact-sm" disabled={candidate.url === null} loading={choosing} onClick={onChoose}>
        Use this one
      </Button>
    </Stack>
  );
}

function ReferenceStrip({
  look,
  onRedo,
  redoingAngle,
}: {
  look: CharacterLook;
  onRedo: (angle: Angle) => void;
  /** The angle whose new picture is being started, if any. */
  redoingAngle: Angle | null;
}) {
  const byAngle = new Map(look.references.map((reference) => [reference.angle, reference]));
  return (
    <SimpleGrid cols={{ base: 2, sm: 5 }} spacing="sm">
      {ANGLES.map((angle) => {
        const reference = byAngle.get(angle);
        const picture = reference ? referencePicture(reference) : null;
        return (
          <Stack key={angle} gap={6}>
            <Text size="sm" fw={500}>
              {ANGLE_LABELS[angle]}
            </Text>
            {picture !== null ? (
              <img src={picture} alt={`${ANGLE_LABELS[angle]} view`} loading="lazy" style={PICTURE_STYLE} />
            ) : (
              <div style={PLACEHOLDER_STYLE}>
                <Loader size="sm" />
                <Text size="xs" c="dimmed">
                  Making...
                </Text>
              </div>
            )}
            {angle === "front" ? (
              <Badge variant="light" color="gray">
                Master
              </Badge>
            ) : (
              <Button
                size="compact-xs"
                variant="default"
                loading={redoingAngle === angle}
                onClick={() => onRedo(angle)}
              >
                Redo
              </Button>
            )}
          </Stack>
        );
      })}
    </SimpleGrid>
  );
}

/**
 * The look step: a look is five pictures of the character on a white backdrop. "Generate looks"
 * makes four candidates to choose from. The one you choose is the master (the front view), and
 * the other four angles are made from it by themselves. Any angle can be made again.
 */
export function LookPicker({ character }: { character: LibraryCharacter }) {
  const looks = useCharacterLooks(character.id);
  const start = useStartLook();
  const choose = useChooseMaster();
  const redo = useRedoAngle();

  const latest = looks.data?.[0] ?? null;
  const busy = latest !== null && lookIsBusy(latest);
  const failure = start.isError
    ? start.error
    : choose.isError
      ? choose.error
      : redo.isError
        ? redo.error
        : null;

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        A look is five pictures of the character on a white backdrop: front, three-quarter,
        profile, back and face. Every picture and clip made with this character starts from them.
      </Text>

      {looks.isLoading && <Loader size="sm" />}
      {looks.isError && (
        <Alert color="red" title="Could not load the looks">
          {describeError(looks.error)}
        </Alert>
      )}

      {latest !== null && latest.id !== character.current_look?.id && character.current_look && (
        <Text size="xs" c="dimmed">
          The character keeps using look {character.current_look.version} until this one is ready.
        </Text>
      )}

      {latest?.status === "writing_prompt" && (
        <Paper withBorder p="sm" radius="md">
          <Group gap="sm">
            <Loader size="sm" />
            <Text size="sm">Writing the master prompt...</Text>
            {latest.prompt_job !== null && <JobStatusBadge job={latest.prompt_job} />}
          </Group>
        </Paper>
      )}

      {latest?.status === "choosing" && (
        <Stack gap="sm">
          <Text size="sm" fw={500}>
            Choose the one you like. It becomes the master.
          </Text>
          <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
            {latest.candidates.map((candidate, index) => (
              <CandidateTile
                key={candidate.id}
                candidate={candidate}
                position={index + 1}
                choosing={choose.isPending && choose.variables?.candidateId === candidate.id}
                onChoose={() => choose.mutate({ lookId: latest.id, candidateId: candidate.id })}
              />
            ))}
          </SimpleGrid>
          <Text size="xs" c="dimmed">
            The pictures take a few minutes. This page updates by itself. If none is right, make
            new looks.
          </Text>
        </Stack>
      )}

      {(latest?.status === "making_angles" || latest?.status === "ready") && (
        <Stack gap="sm">
          <Text size="sm" fw={500}>
            {latest.status === "ready"
              ? `Look ${latest.version} is ready.`
              : "Making the other angles. This page updates by itself."}
          </Text>
          <ReferenceStrip
            look={latest}
            redoingAngle={redo.isPending ? (redo.variables?.angle ?? null) : null}
            onRedo={(angle) => redo.mutate({ lookId: latest.id, angle })}
          />
        </Stack>
      )}

      {latest?.status === "failed" && (
        <Alert color="red" title="This look could not be made">
          {latest.error ?? "No reason was given."}
        </Alert>
      )}

      {failure !== null && (
        <Alert color="red" p="xs">
          {describeError(failure)}
        </Alert>
      )}

      <Stack gap={4} align="flex-start">
        <Button loading={start.isPending} disabled={busy} onClick={() => start.mutate(character.id)}>
          {latest === null ? "Generate looks" : "Generate new looks"}
        </Button>
        <Text size="xs" c="dimmed">
          One call to the language model and four pictures of a few minutes each, then four more
          for the angles. Nothing starts until you press the button. Earlier looks are kept.
        </Text>
      </Stack>
    </Stack>
  );
}
