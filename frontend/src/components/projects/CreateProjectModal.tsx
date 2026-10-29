import { useState } from "react";
import {
  Alert,
  Button,
  Group,
  Modal,
  Radio,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useNavigate } from "react-router";

import { useLibraryCharacters } from "../../api/characterLab";
import { useLibraryEnvironments } from "../../api/environmentLab";
import { describeError } from "../../api/errors";
import { useCreateProject } from "../../api/projects";
import { PROJECT_KINDS, isProjectKind } from "./projectKinds";
import type { ProjectKind } from "./projectKinds";
import { SPEECH_MODES, isSpeechMode } from "./speechModes";
import type { SpeechMode } from "./speechModes";
import { DELIVERY_MAX_CHARS, VOICE_TRACKS, isVoiceTrack } from "./voiceTracks";
import type { VoiceTrack } from "./voiceTracks";

const ORIENTATIONS = [
  { value: "landscape", label: "Landscape", size: "1920 x 1080" },
  { value: "portrait", label: "Portrait", size: "1080 x 1920" },
] as const;

type Orientation = (typeof ORIENTATIONS)[number]["value"];

function isOrientation(value: string): value is Orientation {
  return ORIENTATIONS.some((option) => option.value === value);
}

/**
 * The presenter and the set of an explainer, chosen from the libraries. A character can present
 * only with a saved voice, a visible mouth and a finished look; the server checks the rest.
 */
function PresenterFields({
  presenterId,
  setId,
  onPresenter,
  onSet,
}: {
  presenterId: string | null;
  setId: string | null;
  onPresenter: (value: string | null) => void;
  onSet: (value: string | null) => void;
}) {
  const characters = useLibraryCharacters(false);
  const environments = useLibraryEnvironments(false);
  const characterItems = (characters.data?.pages ?? []).flatMap((page) => page.characters);
  const environmentItems = (environments.data?.pages ?? []).flatMap((page) => page.environments);

  return (
    <>
      <Select
        label="4. Presenter"
        description="A character from the Character Lab with a saved voice and a finished look. It speaks on camera and as the voice-over. It cannot be changed later."
        placeholder="Choose a character"
        searchable
        value={presenterId}
        onChange={onPresenter}
        data={characterItems.map((character) => ({
          value: String(character.id),
          label: character.name,
          disabled:
            character.voice === null ||
            !character.has_visible_mouth ||
            character.current_look?.status !== "ready",
        }))}
        error={characters.isError ? describeError(characters.error) : undefined}
        nothingFoundMessage="No characters"
      />
      {characters.hasNextPage && (
        <Button
          variant="subtle"
          size="xs"
          loading={characters.isFetchingNextPage}
          onClick={() => void characters.fetchNextPage()}
        >
          Load more characters
        </Button>
      )}
      <Select
        label="5. Set (optional)"
        description="An environment from the Environment Lab to speak in. Without one, a studio is designed from the script."
        placeholder="Design a studio from the script"
        clearable
        searchable
        value={setId}
        onChange={onSet}
        data={environmentItems.map((environment) => ({
          value: String(environment.id),
          label: environment.name,
          disabled: environment.image === null,
        }))}
        error={environments.isError ? describeError(environments.error) : undefined}
        nothingFoundMessage="No environments"
      />
      {environments.hasNextPage && (
        <Button
          variant="subtle"
          size="xs"
          loading={environments.isFetchingNextPage}
          onClick={() => void environments.fetchNextPage()}
        >
          Load more environments
        </Button>
      )}
    </>
  );
}

/** Lives inside the modal, so closing the modal throws the form state away. */
function CreateProjectForm({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const create = useCreateProject();
  const [orientation, setOrientation] = useState<Orientation | null>(null);
  const [speechMode, setSpeechMode] = useState<SpeechMode>("both");
  const [kind, setKind] = useState<ProjectKind>("story");
  const [presenterId, setPresenterId] = useState<string | null>(null);
  const [setId, setSetId] = useState<string | null>(null);
  const [captions, setCaptions] = useState(true);
  const [callouts, setCallouts] = useState(true);
  const [voiceTrack, setVoiceTrack] = useState<VoiceTrack>("continuous");
  const [delivery, setDelivery] = useState("");
  const [name, setName] = useState("");

  const canCreate =
    orientation !== null && name.trim() !== "" && (kind === "story" || presenterId !== null);

  function submit() {
    if (orientation === null) {
      return;
    }
    const explainer = kind === "explainer";
    create.mutate(
      {
        name,
        orientation,
        speech_mode: explainer ? "both" : speechMode,
        kind,
        presenter_character_id: explainer && presenterId !== null ? Number(presenterId) : null,
        set_environment_id: explainer && setId !== null ? Number(setId) : null,
        captions: explainer ? captions : true,
        callouts: explainer ? callouts : true,
        // A story sends neither: it is always "lines" and has no delivery text.
        voice_track: explainer ? voiceTrack : undefined,
        presenter_delivery:
          explainer && voiceTrack === "continuous" && delivery.trim() !== "" ? delivery : undefined,
      },
      {
        onSuccess: (project) => {
          onClose();
          void navigate(`/projects/${project.id}`);
        },
      },
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (canCreate) {
          submit();
        }
      }}
    >
      <Stack gap="md">
        <Radio.Group
          label="1. Orientation"
          description="Choose this first. It sets the video size and cannot be changed later."
          value={orientation ?? ""}
          onChange={(value) => {
            if (isOrientation(value)) {
              setOrientation(value);
            }
          }}
        >
          <Group mt="xs" grow align="stretch">
            {ORIENTATIONS.map((option) => (
              <Radio.Card key={option.value} value={option.value} p="md" radius="md">
                <Group wrap="nowrap" align="flex-start">
                  <Radio.Indicator />
                  <Stack gap={2}>
                    <Text fw={500}>{option.label}</Text>
                    <Text size="sm" c="dimmed">
                      {option.size}
                    </Text>
                  </Stack>
                </Group>
              </Radio.Card>
            ))}
          </Group>
        </Radio.Group>

        <TextInput
          label="2. Name"
          value={name}
          onChange={(event) => setName(event.currentTarget.value)}
          maxLength={200}
          data-autofocus
        />

        <Radio.Group
          label="3. Kind"
          description="What the project makes. It cannot be changed later."
          value={kind}
          onChange={(value) => {
            if (isProjectKind(value)) {
              setKind(value);
            }
          }}
        >
          <Stack mt="xs" gap="xs">
            {PROJECT_KINDS.map((option) => (
              <Radio.Card key={option.value} value={option.value} p="md" radius="md">
                <Group wrap="nowrap" align="flex-start">
                  <Radio.Indicator />
                  <Stack gap={2}>
                    <Text fw={500}>{option.label}</Text>
                    <Text size="sm" c="dimmed">
                      {option.description}
                    </Text>
                  </Stack>
                </Group>
              </Radio.Card>
            ))}
          </Stack>
        </Radio.Group>

        {kind === "story" ? (
          <Radio.Group
            label="4. Speech"
            description="How the story is spoken. It cannot be changed later."
            value={speechMode}
            onChange={(value) => {
              if (isSpeechMode(value)) {
                setSpeechMode(value);
              }
            }}
          >
            <Stack mt="xs" gap="xs">
              {SPEECH_MODES.map((option) => (
                <Radio.Card key={option.value} value={option.value} p="md" radius="md">
                  <Group wrap="nowrap" align="flex-start">
                    <Radio.Indicator />
                    <Stack gap={2}>
                      <Text fw={500}>{option.label}</Text>
                      <Text size="sm" c="dimmed">
                        {option.description}
                      </Text>
                    </Stack>
                  </Group>
                </Radio.Card>
              ))}
            </Stack>
          </Radio.Group>
        ) : (
          <>
            <PresenterFields
              presenterId={presenterId}
              setId={setId}
              onPresenter={setPresenterId}
              onSet={setSetId}
            />
            <Radio.Group
              label="6. Voice"
              description="How the presenter's speech is made. It cannot be changed later."
              value={voiceTrack}
              onChange={(value) => {
                if (isVoiceTrack(value)) {
                  setVoiceTrack(value);
                }
              }}
            >
              <Stack mt="xs" gap="xs">
                {VOICE_TRACKS.map((option) => (
                  <Radio.Card key={option.value} value={option.value} p="md" radius="md">
                    <Group wrap="nowrap" align="flex-start">
                      <Radio.Indicator />
                      <Stack gap={2}>
                        <Text fw={500}>{option.label}</Text>
                        <Text size="sm" c="dimmed">
                          {option.description}
                        </Text>
                      </Stack>
                    </Group>
                  </Radio.Card>
                ))}
              </Stack>
            </Radio.Group>
            {voiceTrack === "continuous" && (
              <Textarea
                label="Presenter delivery (optional)"
                description="How the presenter should sound, for example pace and energy. Left empty, the style from the Story Bible is used, or a default. You can change it later in the project settings."
                value={delivery}
                onChange={(event) => setDelivery(event.currentTarget.value)}
                maxLength={DELIVERY_MAX_CHARS}
                autosize
                minRows={2}
                maxRows={6}
              />
            )}
            <Stack gap="xs">
              <Text size="sm" fw={500}>
                7. Captions and callouts
              </Text>
              <Switch
                label="Captions"
                description="Words appear on screen as the presenter speaks them."
                checked={captions}
                onChange={(event) => setCaptions(event.currentTarget.checked)}
              />
              <Switch
                label="Callouts"
                description="Short on-screen highlights, such as key ideas and numbers."
                checked={callouts}
                onChange={(event) => setCallouts(event.currentTarget.checked)}
              />
              <Text size="xs" c="dimmed">
                You can change both later in the project settings.
              </Text>
            </Stack>
          </>
        )}

        {create.isError && <Alert color="red">{describeError(create.error)}</Alert>}

        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button type="submit" disabled={!canCreate} loading={create.isPending}>
            Create project
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function CreateProjectModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  return (
    <Modal opened={opened} onClose={onClose} title="New project" centered>
      <CreateProjectForm onClose={onClose} />
    </Modal>
  );
}
