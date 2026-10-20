import { useState } from "react";
import { Button, Group, Stack, Tabs, Text, Title } from "@mantine/core";
import { Navigate, useNavigate, useParams } from "react-router";

import { CharacterLabPanel } from "../components/characterLab/CharacterLabPanel";
import { EnvironmentLabPanel } from "../components/environmentLab/EnvironmentLabPanel";
import { ImageLabPanel } from "../components/lab/ImageLabPanel";
import { LabLibraryDrawer, type LibraryActions } from "../components/lab/LabLibraryDrawer";
import { VideoLabPanel } from "../components/lab/VideoLabPanel";
import { VoiceLabPanel } from "../components/lab/VoiceLabPanel";
import { DEFAULT_FORM as DEFAULT_IMAGE_FORM, type LabFormState } from "../components/imageLab/labView";
import {
  DEFAULT_FORM as DEFAULT_VIDEO_FORM,
  stateFromRuns,
  type VideoLabFormState,
} from "../components/videoLab/videoLabView";
import {
  DEFAULT_FORM as DEFAULT_VOICE_FORM,
  stateFromRun,
  type VoiceLabFormState,
} from "../components/voiceLab/voiceLabView";

const TABS = [
  { value: "characters", label: "Characters" },
  { value: "environments", label: "Environments" },
  { value: "image", label: "Image" },
  { value: "video", label: "Video" },
  { value: "voice", label: "Voice" },
] as const;

type LabTab = (typeof TABS)[number]["value"];

const DEFAULT_TAB: LabTab = "characters";

function isLabTab(value: string | undefined): value is LabTab {
  return TABS.some((tab) => tab.value === value);
}

/**
 * One place for everything that is tried by hand and belongs to no project: the library of
 * characters (Characters), the library of environments (Environments), and the three labs it
 * is made of (Image, Video, Voice).
 *
 * The tab is in the address (`/lab/characters`), so a tab can be linked to. The Image, Video
 * and Voice forms are kept here, so changing tabs never loses what you typed, and so the
 * library can fill a form of another tab: a picture found in the library becomes a clip's first
 * frame, a speech or a clip is loaded back into its form. The Characters tab keeps nothing
 * here: a character, its looks and what was made with it live on the server, and the open
 * character is in the address (`?character=`).
 */
export function LabPage() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [imageForm, setImageForm] = useState<LabFormState>(DEFAULT_IMAGE_FORM);
  const [videoForm, setVideoForm] = useState<VideoLabFormState>(DEFAULT_VIDEO_FORM);
  const [voiceForm, setVoiceForm] = useState<VoiceLabFormState>(DEFAULT_VOICE_FORM);

  if (!isLabTab(tab)) {
    return <Navigate to={`/lab/${DEFAULT_TAB}`} replace />;
  }

  /** Shows a tab with the form the library just filled in. */
  function show(target: LabTab) {
    setLibraryOpen(false);
    void navigate(`/lab/${target}`);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const actions: LibraryActions = {
    firstFrameForVideo: (item) => {
      // A first frame belongs to the "generate" mode: the reference mode has none.
      setVideoForm((form) => ({
        ...form,
        kind: "generate",
        models: form.kind === "h3_reference" ? DEFAULT_VIDEO_FORM.models : form.models,
        firstFrame: item,
      }));
      show("video");
    },
    loadSpeech: (run) => {
      setVoiceForm(stateFromRun(run));
      show("voice");
    },
    loadClip: (run) => {
      setVideoForm(stateFromRuns([run]));
      show("video");
    },
  };

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Title order={2}>Lab</Title>
          <Text size="sm" c="dimmed" maw={760}>
            Try things by hand. Nothing here belongs to a project. Keep a library of characters
            and make pictures, speech and clips with them, keep a library of places, or try the
            image, video and voice models on their own. The library holds every picture, voice,
            speech and clip, and can send them to a tab.
          </Text>
        </Stack>
        <Button variant="default" onClick={() => setLibraryOpen(true)}>
          Library
        </Button>
      </Group>

      <Tabs value={tab} onChange={(value) => value !== null && void navigate(`/lab/${value}`)}>
        <Tabs.List>
          {TABS.map((item) => (
            <Tabs.Tab key={item.value} value={item.value}>
              {item.label}
            </Tabs.Tab>
          ))}
        </Tabs.List>

        {/* Every panel stays mounted, so a result shown on a tab is still there when you return. */}
        <Tabs.Panel value="characters" pt="md">
          <CharacterLabPanel />
        </Tabs.Panel>
        <Tabs.Panel value="environments" pt="md">
          <EnvironmentLabPanel />
        </Tabs.Panel>
        <Tabs.Panel value="image" pt="md">
          <ImageLabPanel form={imageForm} onFormChange={setImageForm} />
        </Tabs.Panel>
        <Tabs.Panel value="video" pt="md">
          <VideoLabPanel form={videoForm} onFormChange={setVideoForm} />
        </Tabs.Panel>
        <Tabs.Panel value="voice" pt="md">
          <VoiceLabPanel form={voiceForm} onFormChange={setVoiceForm} />
        </Tabs.Panel>
      </Tabs>

      <LabLibraryDrawer
        opened={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        actions={actions}
      />
    </Stack>
  );
}
