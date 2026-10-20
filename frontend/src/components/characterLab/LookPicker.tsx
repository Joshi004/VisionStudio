import {
  Alert,
  Badge,
  Button,
  FileButton,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { useRef } from "react";

import {
  lookIsBusy,
  useChooseMaster,
  useCharacterLooks,
  useRedoAngle,
  useSetCurrentLook,
  useStartLook,
  useStartLookFromPicture,
  type Angle,
  type CharacterLook,
  type LibraryCharacter,
  type LookCandidate,
} from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { LAB_UPLOAD_MAX_MB, useLabUpload } from "../../api/imageLab";
import { ACCEPT } from "../imageLab/ReferenceTray";
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

/**
 * The five angle pictures of a look. Without `onRedo` there are no Redo buttons (the story
 * workspace shows the strip with its own).
 */
export function ReferenceStrip({
  look,
  onRedo,
  redoingAngle = null,
}: {
  look: CharacterLook;
  onRedo?: (angle: Angle) => void;
  /** The angle whose new picture is being started, if any. */
  redoingAngle?: Angle | null;
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
              onRedo !== undefined && (
                <Button
                  size="compact-xs"
                  variant="default"
                  loading={redoingAngle === angle}
                  onClick={() => onRedo(angle)}
                >
                  Redo
                </Button>
              )
            )}
          </Stack>
        );
      })}
    </SimpleGrid>
  );
}

function EarlierLookTile({
  look,
  onUse,
  using,
  disabled,
}: {
  look: CharacterLook;
  onUse: () => void;
  using: boolean;
  disabled: boolean;
}) {
  const front = look.references.find((reference) => reference.angle === "front");
  const picture = front ? referencePicture(front) : null;
  return (
    <Stack gap={6}>
      {picture !== null ? (
        <img src={picture} alt={`Look ${look.version}`} loading="lazy" style={PICTURE_STYLE} />
      ) : (
        <div style={PLACEHOLDER_STYLE} />
      )}
      <Text size="sm" fw={500}>
        Look {look.version}
      </Text>
      <Button size="compact-sm" variant="default" loading={using} disabled={disabled} onClick={onUse}>
        Use this look
      </Button>
    </Stack>
  );
}

/**
 * The look step: a look is five pictures of the character on a white backdrop. "Generate looks"
 * makes four candidates to choose from; "Generate from my picture" makes the four from the
 * author's own picture instead. The one you choose is the master (the front view), and the other
 * four angles are made from it by themselves. Any angle can be made again. An earlier ready look
 * can be made the current one again; the character then has a new version.
 */
export function LookPicker({ character }: { character: LibraryCharacter }) {
  const looks = useCharacterLooks(character.id);
  const start = useStartLook();
  const upload = useLabUpload();
  const startFromPicture = useStartLookFromPicture();
  const choose = useChooseMaster();
  const redo = useRedoAngle();
  const setCurrent = useSetCurrentLook();
  // Lets the same file be picked again after a failed upload.
  const resetFileButton = useRef<() => void>(null);

  const latest = looks.data?.[0] ?? null;
  const busy = latest !== null && lookIsBusy(latest);
  const pictureBusy = upload.isPending || startFromPicture.isPending;
  // The ready looks the character is not using now.
  const earlierLooks = (looks.data ?? []).filter(
    (look) => look.status === "ready" && look.id !== character.current_look?.id,
  );
  const failure = start.isError
    ? start.error
    : upload.isError
      ? upload.error
      : startFromPicture.isError
        ? startFromPicture.error
        : choose.isError
          ? choose.error
          : redo.isError
            ? redo.error
            : setCurrent.isError
              ? setCurrent.error
              : null;

  function chooseFile(file: File | null) {
    resetFileButton.current?.();
    if (file) {
      upload.mutate(file, {
        onSuccess: (image) => startFromPicture.mutate({ characterId: character.id, imageId: image.id }),
      });
    }
  }

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

      {latest !== null &&
        latest.status !== "ready" &&
        latest.id !== character.current_look?.id &&
        character.current_look && (
        <Text size="xs" c="dimmed">
          The character keeps using look {character.current_look.version} until this one is ready.
        </Text>
      )}

      {latest?.reference_url && (latest.status === "writing_prompt" || latest.status === "choosing") && (
        <Group gap="sm">
          <img
            src={latest.reference_url}
            alt="Your picture"
            style={{ ...PICTURE_STYLE, width: 64 }}
          />
          <Text size="xs" c="dimmed">
            Made from your picture.
          </Text>
        </Group>
      )}

      {latest?.status === "waiting" && (
        <Paper withBorder p="sm" radius="md">
          <Group gap="sm">
            <Loader size="sm" />
            <Text size="sm">
              Waiting for the picture of another character in the story to be ready...
            </Text>
          </Group>
        </Paper>
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

      {earlierLooks.length > 0 && (
        <Stack gap="sm">
          <Text size="sm" fw={500}>
            Earlier looks
          </Text>
          <Text size="xs" c="dimmed">
            {character.current_look
              ? `The character uses look ${character.current_look.version}. `
              : ""}
            Use an earlier look to make new pictures and clips from it. This adds a new version of
            the character; nothing is lost.
          </Text>
          <SimpleGrid cols={{ base: 3, sm: 5 }} spacing="sm">
            {earlierLooks.map((look) => (
              <EarlierLookTile
                key={look.id}
                look={look}
                using={setCurrent.isPending && setCurrent.variables?.lookId === look.id}
                disabled={setCurrent.isPending}
                onUse={() => setCurrent.mutate({ characterId: character.id, lookId: look.id })}
              />
            ))}
          </SimpleGrid>
        </Stack>
      )}

      {failure !== null && (
        <Alert color="red" p="xs">
          {describeError(failure)}
        </Alert>
      )}

      <Stack gap={4} align="flex-start">
        <Group gap="sm">
          <Button
            loading={start.isPending}
            disabled={busy || pictureBusy}
            onClick={() => start.mutate(character.id)}
          >
            {latest === null ? "Generate looks" : "Generate new looks"}
          </Button>
          <FileButton resetRef={resetFileButton} onChange={chooseFile} accept={ACCEPT}>
            {(props) => (
              <Button
                {...props}
                variant="default"
                loading={pictureBusy}
                disabled={busy || start.isPending}
              >
                Generate from my picture
              </Button>
            )}
          </FileButton>
        </Group>
        <Text size="xs" c="dimmed">
          One call to the language model and four pictures of a few minutes each, then four more
          for the angles. Nothing starts until you press the button. Earlier looks are kept.
        </Text>
        <Text size="xs" c="dimmed">
          From your picture (PNG, JPEG or WebP, up to {LAB_UPLOAD_MAX_MB} MB): the four candidates
          keep its face, hair and build, and wear the outfit from the profile.
        </Text>
      </Stack>
    </Stack>
  );
}
