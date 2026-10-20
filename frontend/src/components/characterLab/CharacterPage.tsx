import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Grid,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import {
  lookIsBusy,
  useCharacterLooks,
  useEditCharacter,
  useLibraryCharacter,
  type CharacterTake,
  type LibraryCharacter,
} from "../../api/characterLab";
import { describeError } from "../../api/errors";
import { CreatePanel } from "./CreatePanel";
import { LOOK_STEP, PROFILE_STEP, VOICE_STEP, type DrawerStep } from "./CharacterDrawer";
import {
  ANGLE_LABELS,
  ANGLES,
  characterSubtitle,
  CREATE_PANEL_ID,
  DEFAULT_TAKE_FORM,
  eraText,
  referencePicture,
  takeToForm,
  type TakeFormState,
} from "./characterLabView";
import { TakeGallery } from "./TakeGallery";
import { UsedByProjects } from "./UsedByProjects";
import { VersionHistory } from "./VersionHistory";

type CharacterPageProps = {
  characterId: number;
  onBack: () => void;
  /** Opens the drawer at this step. */
  onEdit: (step: DrawerStep) => void;
};

const PICTURE_STYLE = {
  width: "100%",
  aspectRatio: "2 / 3",
  objectFit: "contain",
  background: "var(--mantine-color-gray-1)",
  borderRadius: 4,
  display: "block",
} as const;

function Detail({ label, value }: { label: string; value: string | null }) {
  if (value === null || value.trim() === "") {
    return null;
  }
  return (
    <Text size="sm">
      <Text span fw={500}>
        {label}:{" "}
      </Text>
      {value}
    </Text>
  );
}

function References({ character }: { character: LibraryCharacter }) {
  const look = character.current_look;
  if (look === null) {
    return (
      <Text size="sm" c="dimmed">
        No look yet. Press New look to make the five pictures every picture and clip starts from.
      </Text>
    );
  }
  const byAngle = new Map(look.references.map((reference) => [reference.angle, reference]));
  return (
    <SimpleGrid cols={{ base: 3, sm: 5, lg: 3 }} spacing="xs">
      {ANGLES.map((angle) => {
        const reference = byAngle.get(angle);
        const picture = reference ? referencePicture(reference) : null;
        return (
          <Stack key={angle} gap={2}>
            {picture !== null ? (
              <img src={picture} alt={`${ANGLE_LABELS[angle]} view`} loading="lazy" style={PICTURE_STYLE} />
            ) : (
              <div style={{ ...PICTURE_STYLE, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Loader size="xs" />
              </div>
            )}
            <Text size="xs" c="dimmed" ta="center">
              {ANGLE_LABELS[angle]}
            </Text>
          </Stack>
        );
      })}
    </SimpleGrid>
  );
}

/**
 * One character: its profile and pictures on the left; on the right, the Create panel and
 * everything made with it. The profile, the look and the voice are changed in the drawer.
 */
export function CharacterPage({ characterId, onBack, onEdit }: CharacterPageProps) {
  const character = useLibraryCharacter(characterId);
  // Followed here too, so a look that is made after the drawer is closed still shows up.
  const looks = useCharacterLooks(characterId);
  const edit = useEditCharacter();
  // The Create panel's form lives here, so a take in the gallery can fill it.
  const [takeForm, setTakeForm] = useState<TakeFormState>(DEFAULT_TAKE_FORM);

  function reuseTake(take: CharacterTake) {
    setTakeForm(takeToForm(take));
    document.getElementById(CREATE_PANEL_ID)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const back = (
    <Group>
      <Button variant="subtle" size="compact-sm" onClick={onBack}>
        Back to the characters
      </Button>
    </Group>
  );

  if (character.isLoading) {
    return (
      <Stack gap="md">
        {back}
        <Loader size="sm" />
      </Stack>
    );
  }
  if (character.isError || !character.data) {
    return (
      <Stack gap="md">
        {back}
        <Alert color="red" title="Could not open the character">
          {describeError(character.error)}
        </Alert>
      </Stack>
    );
  }

  const data = character.data;
  const newest = looks.data?.[0] ?? null;
  const lookInProgress = newest !== null && lookIsBusy(newest);

  return (
    <Stack gap="md">
      {back}
      <Grid gap="lg">
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <Paper withBorder p="md" radius="md">
            <Stack gap="md">
              <Stack gap={4}>
                <Group gap="xs" align="center">
                  <Title order={3}>{data.name}</Title>
                  {data.version !== null && (
                    <Badge variant="light" color="blue" title="The newest version of this character">
                      v{data.version}
                    </Badge>
                  )}
                  {data.voice !== null ? (
                    <Badge variant="light" color="grape">
                      voice: {data.voice.name}
                    </Badge>
                  ) : (
                    <Badge variant="light" color="gray">
                      mute
                    </Badge>
                  )}
                  {data.archived && (
                    <Badge variant="light" color="orange">
                      archived
                    </Badge>
                  )}
                  {data.origin !== null && (
                    <Badge
                      variant="light"
                      color="teal"
                      title={`Made from the character "${data.origin.discovery_id}" of the project ${data.origin.project_name}`}
                    >
                      from project: {data.origin.project_name}
                    </Badge>
                  )}
                </Group>
                <Text size="sm" c="dimmed">
                  {characterSubtitle(data)}
                </Text>
              </Stack>

              <Group gap="xs">
                <Button size="compact-sm" variant="default" onClick={() => onEdit(PROFILE_STEP)}>
                  Edit
                </Button>
                <Button size="compact-sm" variant="default" onClick={() => onEdit(LOOK_STEP)}>
                  New look
                </Button>
                <Button size="compact-sm" variant="default" onClick={() => onEdit(VOICE_STEP)}>
                  Voice
                </Button>
                <Button
                  size="compact-sm"
                  variant="subtle"
                  color="orange"
                  loading={edit.isPending}
                  onClick={() => edit.mutate({ characterId: data.id, body: { archived: !data.archived } })}
                >
                  {data.archived ? "Unarchive" : "Archive"}
                </Button>
              </Group>
              {edit.isError && (
                <Alert color="red" p="xs">
                  {describeError(edit.error)}
                </Alert>
              )}

              {lookInProgress && (
                <Alert color="blue" p="xs" title="A new look is being made">
                  <Group gap="xs">
                    <Text size="sm">
                      {newest.status === "choosing"
                        ? "Choose a master picture."
                        : "It becomes the character's look when it is ready."}
                    </Text>
                    <Button size="compact-xs" variant="light" onClick={() => onEdit(LOOK_STEP)}>
                      Open
                    </Button>
                  </Group>
                </Alert>
              )}

              <References character={data} />

              <Stack gap={4}>
                <Detail label="Era" value={eraText(data)} />
                <Detail label="Appearance" value={data.appearance} />
                <Detail label="Outfit" value={data.outfit} />
                <Detail label="Personality" value={data.personality} />
                <Detail label="Notes" value={data.notes} />
                <Detail label="Voice description" value={data.voice_description} />
                <Detail label="Mouth" value={data.has_visible_mouth ? "visible" : "not visible (no lip sync)"} />
              </Stack>

              <UsedByProjects characterId={data.id} />

              <VersionHistory characterId={data.id} />
            </Stack>
          </Paper>
        </Grid.Col>

        <Grid.Col span={{ base: 12, lg: 8 }}>
          <Stack gap="lg">
            <CreatePanel character={data} form={takeForm} onChange={setTakeForm} />
            <TakeGallery characterId={data.id} onReuse={reuseTake} />
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
