import { useState } from "react";
import { Button, Group, Stack, Tabs, Text, Title } from "@mantine/core";
import { Navigate, useNavigate, useParams } from "react-router";

import { ImageLabPanel } from "../components/lab/ImageLabPanel";
import { LabLibraryDrawer, type LibraryActions } from "../components/lab/LabLibraryDrawer";
import { VideoLabPanel } from "../components/lab/VideoLabPanel";
import { VoiceLabPanel } from "../components/lab/VoiceLabPanel";
import { DEFAULT_FORM as DEFAULT_IMAGE_FORM, type LabFormState } from "../components/imageLab/labView";
import { TalkLabPanel } from "../components/talkLab/TalkLabPanel";
import {
  DEFAULT_FORM as DEFAULT_TALK_FORM,
  withCharacter,
  type TalkFormState,
} from "../components/talkLab/talkLabView";
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
  { value: "talk", label: "Talking character" },
  { value: "image", label: "Image" },
  { value: "video", label: "Video" },
  { value: "voice", label: "Voice" },
] as const;

type LabTab = (typeof TABS)[number]["value"];

function isLabTab(value: string | undefined): value is LabTab {
  return TABS.some((tab) => tab.value === value);
}

/**
 * One place for everything that is tried by hand and belongs to no project: a character that
 * speaks a line (Talking character), and the three labs it is made of (Image, Video, Voice).
 *
 * The tab is in the address (`/lab/talk`), so a tab can be linked to. Every tab's form is kept
 * here, so changing tabs never loses what you typed, and so the library can fill a form of
 * another tab: a picture found in the library becomes the character's picture, a speech
 * becomes the speech of a take, and so on.
 */
export function LabPage() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [talkForm, setTalkForm] = useState<TalkFormState>(DEFAULT_TALK_FORM);
  const [imageForm, setImageForm] = useState<LabFormState>(DEFAULT_IMAGE_FORM);
  const [videoForm, setVideoForm] = useState<VideoLabFormState>(DEFAULT_VIDEO_FORM);
  const [voiceForm, setVoiceForm] = useState<VoiceLabFormState>(DEFAULT_VOICE_FORM);

  if (!isLabTab(tab)) {
    return <Navigate to="/lab/talk" replace />;
  }

  /** Shows a tab with the form the library just filled in. */
  function show(target: LabTab) {
    setLibraryOpen(false);
    void navigate(`/lab/${target}`);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const actions: LibraryActions = {
    pictureForTalk: (item) => {
      // A picture of its own is not a cast character's picture any more.
      setTalkForm((form) => ({ ...form, image: item, characterId: null }));
      show("talk");
    },
    characterForTalk: (character) => {
      setTalkForm((form) => withCharacter(form, character));
      show("talk");
    },
    voiceForTalk: (voice) => {
      setTalkForm((form) => ({
        ...form,
        speech: "new",
        voiceMode: form.voiceMode === "direction" ? "direction" : "clone",
        voiceId: String(voice.id),
      }));
      show("talk");
    },
    speechForTalk: (run) => {
      setTalkForm((form) => ({ ...form, speech: "reuse", reuseRunId: String(run.id) }));
      show("talk");
    },
    firstFrameForVideo: (item) => {
      setVideoForm((form) => ({ ...form, firstFrame: item }));
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
            Try things by hand. Nothing here belongs to a project. Make a character speak a line
            of dialogue, or try the image, video and voice models on their own. The library holds
            every picture, voice, speech and clip, and can send any of them to a tab.
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
        <Tabs.Panel value="talk" pt="md">
          <TalkLabPanel form={talkForm} onFormChange={setTalkForm} />
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
