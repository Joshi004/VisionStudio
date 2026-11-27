import { useEffect, useState } from "react";
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

import {
  useCharacterOutfits,
  useLibraryCharacter,
  useLibraryCharacters,
} from "../../api/characterLab";
import { useLibraryEnvironment, useLibraryEnvironments } from "../../api/environmentLab";
import { ApiError, describeError } from "../../api/errors";
import { useCreateProject } from "../../api/projects";
import { PresenterOutfitField } from "./PresenterOutfitField";
import { CALLOUT_STYLES, isCalloutStyle } from "./calloutStyles";
import type { CalloutStyle } from "./calloutStyles";
import { CAPTION_MODES, isCaptionMode } from "./captionModes";
import type { CaptionMode } from "./captionModes";
import {
  DEFAULT_SETTINGS,
  clearLastSettings,
  readLastSettings,
  writeLastSettings,
} from "./lastProjectSettings";
import type { NewProjectSettings } from "./lastProjectSettings";
import { ORIENTATIONS, isOrientation } from "./orientations";
import type { Orientation } from "./orientations";
import { PROJECT_KINDS, STAGING_MAX_CHARS, isProjectKind } from "./projectKinds";
import type { ProjectKind } from "./projectKinds";
import { SPEECH_MODES, isSpeechMode } from "./speechModes";
import type { SpeechMode } from "./speechModes";
import { TAKE_SOURCES, isTakeSource } from "./takeSources";
import type { TakeSource } from "./takeSources";
import { DELIVERY_MAX_CHARS, VOICE_TRACKS, isVoiceTrack } from "./voiceTracks";
import type { VoiceTrack } from "./voiceTracks";

/** A character can present only with a saved voice, a visible mouth and a finished look. */
function canPresent(character: {
  voice: object | null;
  has_visible_mouth: boolean;
  current_look: { status: string } | null;
}): boolean {
  return (
    character.voice !== null &&
    character.has_visible_mouth &&
    character.current_look?.status === "ready"
  );
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

  // A presenter or set from the last project may be past the first page of the list, so it is
  // loaded by its id. One that was deleted, archived or is no longer usable is cleared.
  const listedCharacter = characterItems.find((item) => String(item.id) === presenterId);
  const savedCharacter = useLibraryCharacter(
    presenterId !== null && characters.isSuccess && listedCharacter === undefined
      ? Number(presenterId)
      : null,
  );
  const presenter = listedCharacter ?? savedCharacter.data;
  const presenterGone =
    presenter !== undefined
      ? presenter.archived || !canPresent(presenter)
      : savedCharacter.error instanceof ApiError && savedCharacter.error.status === 404;
  useEffect(() => {
    if (presenterGone) {
      onPresenter(null);
    }
  }, [presenterGone, onPresenter]);

  const listedEnvironment = environmentItems.find((item) => String(item.id) === setId);
  const savedEnvironment = useLibraryEnvironment(
    setId !== null && environments.isSuccess && listedEnvironment === undefined
      ? Number(setId)
      : null,
  );
  const set = listedEnvironment ?? savedEnvironment.data;
  const setGone =
    set !== undefined
      ? set.archived || set.image === null
      : savedEnvironment.error instanceof ApiError && savedEnvironment.error.status === 404;
  useEffect(() => {
    if (setGone) {
      onSet(null);
    }
  }, [setGone, onSet]);

  const characterOptions = characterItems.map((character) => ({
    value: String(character.id),
    label: character.name,
    disabled: !canPresent(character),
  }));
  if (listedCharacter === undefined && presenter !== undefined && !presenterGone) {
    characterOptions.push({ value: String(presenter.id), label: presenter.name, disabled: false });
  }
  const environmentOptions = environmentItems.map((environment) => ({
    value: String(environment.id),
    label: environment.name,
    disabled: environment.image === null,
  }));
  if (listedEnvironment === undefined && set !== undefined && !setGone) {
    environmentOptions.push({ value: String(set.id), label: set.name, disabled: false });
  }

  return (
    <>
      <Select
        label="4. Presenter"
        description="A character from the Character Lab with a saved voice and a finished look. It speaks on camera and as the voice-over. It cannot be changed later."
        placeholder="Choose a character"
        searchable
        value={presenterId}
        onChange={onPresenter}
        data={characterOptions}
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
        data={environmentOptions}
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
  // The settings of the last project that was created; the name is always new.
  const [initial] = useState(readLastSettings);
  const [orientation, setOrientation] = useState<Orientation | null>(initial.orientation);
  const [speechMode, setSpeechMode] = useState<SpeechMode>(initial.speechMode);
  const [kind, setKind] = useState<ProjectKind>(initial.kind);
  const [presenterId, setPresenterId] = useState<string | null>(initial.presenterId);
  const [setId, setSetId] = useState<string | null>(initial.setId);
  const [captionMode, setCaptionMode] = useState<CaptionMode>(initial.captionMode);
  const [callouts, setCallouts] = useState(initial.callouts);
  const [calloutStyle, setCalloutStyle] = useState<CalloutStyle>(initial.calloutStyle);
  const [voiceTrack, setVoiceTrack] = useState<VoiceTrack>(initial.voiceTrack);
  const [takeSource, setTakeSource] = useState<TakeSource>(initial.takeSource);
  const [delivery, setDelivery] = useState(initial.delivery);
  const [staging, setStaging] = useState(initial.staging);
  const [outfit, setOutfit] = useState(initial.outfit);
  const [outfitId, setOutfitId] = useState<number | null>(initial.outfitId);
  const [graphics, setGraphics] = useState(initial.graphics);
  const [evidence, setEvidence] = useState(initial.evidence);
  const [soundEffects, setSoundEffects] = useState(initial.soundEffects);
  const [footage, setFootage] = useState(initial.footage);
  const [name, setName] = useState("");

  // A saved outfit is only kept while it is still one of the presenter's saved outfits.
  const presenterOutfits = useCharacterOutfits(presenterId === null ? null : Number(presenterId));
  const savedOutfits = presenterOutfits.data;
  const outfitIsGone =
    outfitId !== null &&
    savedOutfits !== undefined &&
    !savedOutfits.some((item) => item.id === outfitId);
  if (outfitIsGone) {
    setOutfitId(null);
  }

  function applySettings(settings: NewProjectSettings) {
    setOrientation(settings.orientation);
    setSpeechMode(settings.speechMode);
    setKind(settings.kind);
    setPresenterId(settings.presenterId);
    setSetId(settings.setId);
    setCaptionMode(settings.captionMode);
    setCallouts(settings.callouts);
    setCalloutStyle(settings.calloutStyle);
    setVoiceTrack(settings.voiceTrack);
    setTakeSource(settings.takeSource);
    setDelivery(settings.delivery);
    setStaging(settings.staging);
    setOutfit(settings.outfit);
    setOutfitId(settings.outfitId);
    setGraphics(settings.graphics);
    setEvidence(settings.evidence);
    setSoundEffects(settings.soundEffects);
    setFootage(settings.footage);
  }

  function resetToDefaults() {
    clearLastSettings();
    applySettings(DEFAULT_SETTINGS);
  }

  // Motion callouts are only for a continuous explainer with graphics and callouts on.
  const canChooseCalloutStyle =
    kind === "explainer" && voiceTrack === "continuous" && graphics && callouts;

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
        caption_mode: explainer ? captionMode : "burned",
        callouts: explainer ? callouts : true,
        callout_style: canChooseCalloutStyle ? calloutStyle : "boxes",
        // A story sends neither: it is always "lines" and has no delivery text.
        voice_track: explainer ? voiceTrack : undefined,
        // Only a continuous explainer has a voice source; the delivery text is for generated voice.
        take_source: explainer && voiceTrack === "continuous" ? takeSource : undefined,
        presenter_delivery:
          explainer &&
          voiceTrack === "continuous" &&
          takeSource === "generated" &&
          delivery.trim() !== ""
            ? delivery
            : undefined,
        presenter_staging: explainer && staging.trim() !== "" ? staging : undefined,
        presenter_outfit:
          explainer && outfitId === null && outfit.trim() !== "" ? outfit : undefined,
        presenter_named_look_id: explainer && outfitId !== null ? outfitId : undefined,
        // Only a continuous explainer can have graphics; any other project leaves it out.
        graphics: explainer && voiceTrack === "continuous" ? graphics : undefined,
        // Only a continuous explainer can have evidence; any other project leaves it out.
        evidence: explainer && voiceTrack === "continuous" ? evidence : undefined,
        // Only a continuous explainer can have sound effects; any other project leaves it out.
        sound_effects: explainer && voiceTrack === "continuous" ? soundEffects : undefined,
        // Only a continuous explainer can have footage; any other project leaves it out.
        footage: explainer && voiceTrack === "continuous" ? footage : undefined,
      },
      {
        onSuccess: (project) => {
          writeLastSettings({
            orientation,
            kind,
            speechMode,
            presenterId,
            setId,
            staging,
            outfitId,
            outfit,
            voiceTrack,
            takeSource,
            delivery,
            graphics,
            evidence,
            soundEffects,
            footage,
            captionMode,
            callouts,
            calloutStyle,
          });
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
              onPresenter={(value) => {
                setPresenterId(value);
                // The saved outfits belong to the presenter, so a pick does not carry over.
                setOutfitId(null);
              }}
              onSet={setSetId}
            />
            <Textarea
              label="Presenter staging (optional)"
              description="How the presenter is placed and moves on camera, for example: seated at a desk, hands on the desk, little movement. Left empty, the presenter stands. You can change it later in the project settings."
              value={staging}
              onChange={(event) => setStaging(event.currentTarget.value)}
              maxLength={STAGING_MAX_CHARS}
              autosize
              minRows={2}
              maxRows={6}
            />
            <PresenterOutfitField
              key={presenterId ?? "none"}
              characterId={presenterId === null ? null : Number(presenterId)}
              pickedId={outfitId}
              text={outfit}
              onChange={(value) => {
                setOutfitId(value.pickedId);
                setOutfit(value.text);
              }}
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
              <Radio.Group
                label="Voice source"
                description="Who speaks the script. You can change it later in the project settings."
                value={takeSource}
                onChange={(value) => {
                  if (isTakeSource(value)) {
                    setTakeSource(value);
                  }
                }}
              >
                <Stack mt="xs" gap="xs">
                  {TAKE_SOURCES.map((option) => (
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
            )}
            {voiceTrack === "continuous" && takeSource === "generated" && (
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
            {voiceTrack === "continuous" && (
              <Switch
                label="Graphics"
                description="Charts, diagrams and text cards drawn by code and timed to the presenter's words, for numbers, comparisons, steps and lists. It cannot be changed later."
                checked={graphics}
                onChange={(event) => setGraphics(event.currentTarget.checked)}
              />
            )}
            {voiceTrack === "continuous" && (
              <Switch
                label="Evidence"
                description="Proof on screen for the claims that can be checked: a price, a figure from a report, something a person said. You mark the claims, research them with Cursor or Claude, and review every piece of evidence. You can change it later in the project settings."
                checked={evidence}
                onChange={(event) => setEvidence(event.currentTarget.checked)}
              />
            )}
            {voiceTrack === "continuous" && (
              <Switch
                label="Footage"
                description="Real pictures shown full screen while the narrator talks: a few seconds of an event from an official channel, a press photo, a web page, or a file of your own. You mark the words and say what to show, research them with Cursor or Claude, and review every piece. You can change it later in the project settings."
                checked={footage}
                onChange={(event) => setFootage(event.currentTarget.checked)}
              />
            )}
            {voiceTrack === "continuous" && (
              <Switch
                label="Sound effects"
                description="A soft sound at every graphic and every piece of evidence, made once for the project: you listen to the takes and choose. It only plays in projects with graphics or evidence. You can change it later in the project settings."
                checked={soundEffects}
                onChange={(event) => setSoundEffects(event.currentTarget.checked)}
              />
            )}
            <Stack gap="xs">
              <Text size="sm" fw={500}>
                7. Captions and callouts
              </Text>
              <Radio.Group
                label="Captions"
                description="The words are timed to the presenter's voice either way."
                value={captionMode}
                onChange={(value) => {
                  if (isCaptionMode(value)) {
                    setCaptionMode(value);
                  }
                }}
              >
                <Stack mt="xs" gap="xs">
                  {CAPTION_MODES.map((option) => (
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
              <Switch
                label="Callouts"
                description="Short on-screen highlights, such as key ideas and numbers."
                checked={callouts}
                onChange={(event) => setCallouts(event.currentTarget.checked)}
              />
              {canChooseCalloutStyle && (
                <Radio.Group
                  label="Callout style"
                  value={calloutStyle}
                  onChange={(value) => {
                    if (isCalloutStyle(value)) {
                      setCalloutStyle(value);
                    }
                  }}
                >
                  <Stack mt="xs" gap="xs">
                    {CALLOUT_STYLES.map((option) => (
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
              )}
              <Text size="xs" c="dimmed">
                You can change both later in the project settings.
              </Text>
            </Stack>
          </>
        )}

        {create.isError && <Alert color="red">{describeError(create.error)}</Alert>}

        <Group justify="space-between">
          <Button
            variant="subtle"
            color="gray"
            onClick={resetToDefaults}
            disabled={create.isPending}
          >
            Reset to defaults
          </Button>
          <Group>
            <Button variant="default" onClick={onClose} disabled={create.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canCreate} loading={create.isPending}>
              Create project
            </Button>
          </Group>
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
