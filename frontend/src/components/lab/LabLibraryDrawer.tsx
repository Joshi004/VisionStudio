import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Drawer,
  Group,
  Loader,
  Paper,
  Select,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import { useLabLibrary, useProjectFrames } from "../../api/imageLab";
import { useProjects } from "../../api/projects";
import { useLabVideoRuns, type LabVideoRun } from "../../api/videoLab";
import { useVoiceLabRuns, useVoices, type VoiceLabRun } from "../../api/voiceLab";
import { formatDateTime } from "../../format";
import { referenceFromFrame, referenceFromImage, type ReferenceItem } from "../imageLab/labView";
import { Thumb } from "../imageLab/ReferenceTray";
import { isLipSyncRun, isReferenceRun } from "../videoLab/videoLabView";
import { paramsLine as speechParamsLine } from "../voiceLab/voiceLabView";

/**
 * What the library can do with an item: send it to the tab that can use it. The Lab page
 * implements them, because it holds every tab's form. The Characters tab keeps its own state
 * (a character, its looks and takes live on the server), so nothing is sent to it from here.
 */
export type LibraryActions = {
  /** Make this image the first frame of a Video lab clip. */
  firstFrameForVideo: (item: ReferenceItem) => void;
  /** Put this speech's text and settings back into the Voice form. */
  loadSpeech: (run: VoiceLabRun) => void;
  /** Put this clip's prompt and settings back into the Video form. */
  loadClip: (run: LabVideoRun) => void;
};

type LabLibraryDrawerProps = {
  opened: boolean;
  onClose: () => void;
  actions: LibraryActions;
};

function Empty({ children }: { children: string }) {
  return (
    <Text size="sm" c="dimmed">
      {children}
    </Text>
  );
}

function LoadError({ title, error }: { title: string; error: unknown }) {
  return (
    <Alert color="red" title={title}>
      {describeError(error)} Press Refresh to try again.
    </Alert>
  );
}

function MoreButton({
  query,
}: {
  query: { hasNextPage: boolean; isFetchingNextPage: boolean; fetchNextPage: () => unknown };
}) {
  if (!query.hasNextPage) {
    return null;
  }
  return (
    <Button
      variant="default"
      loading={query.isFetchingNextPage}
      onClick={() => void query.fetchNextPage()}
    >
      Older
    </Button>
  );
}

// --- Images ----------------------------------------------------------------------------------

function ImageCard({
  item,
  caption,
  actions,
}: {
  item: ReferenceItem;
  caption: string;
  actions: LibraryActions;
}) {
  return (
    <Stack gap={4}>
      <Thumb url={item.url} width={item.width} height={item.height} />
      <Text size="xs" c="dimmed" lineClamp={1} title={caption}>
        {caption}
      </Text>
      <Button size="compact-xs" variant="default" onClick={() => actions.firstFrameForVideo(item)}>
        Video first frame
      </Button>
    </Stack>
  );
}

function ImagesSection({ actions }: { actions: LibraryActions }) {
  const [source, setSource] = useState<"lab" | "project">("lab");
  const [projectId, setProjectId] = useState<string | null>(null);
  const library = useLabLibrary(true);
  const projects = useProjects();
  const frames = useProjectFrames(projectId === null ? null : Number(projectId));

  return (
    <Stack gap="sm">
      <SegmentedControl
        value={source}
        onChange={(value) => setSource(value === "project" ? "project" : "lab")}
        data={[
          { value: "lab", label: "Lab images" },
          { value: "project", label: "Project frames" },
        ]}
      />
      {source === "lab" ? (
        <>
          <Text size="sm" c="dimmed">
            The newest 60 lab images: your uploads and the results of the Image lab.
          </Text>
          {library.isLoading && <Loader size="sm" />}
          {library.isError && <LoadError title="Could not load the images" error={library.error} />}
          {library.data?.length === 0 && <Empty>No images yet. Upload one, or make a run.</Empty>}
          <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm">
            {library.data?.map((image) => (
              <ImageCard
                key={image.id}
                item={referenceFromImage(image)}
                caption={
                  image.origin === "upload" ? `upload ${image.id}` : `result of run ${image.run_id ?? "?"}`
                }
                actions={actions}
              />
            ))}
          </SimpleGrid>
        </>
      ) : (
        <>
          <Select
            label="Project"
            placeholder="Choose a project"
            data={(projects.data ?? []).map((project) => ({
              value: String(project.id),
              label: project.name,
            }))}
            value={projectId}
            onChange={setProjectId}
            searchable
            nothingFoundMessage="No projects"
          />
          {frames.isLoading && <Loader size="sm" />}
          {frames.isError && <LoadError title="Could not load the frames" error={frames.error} />}
          {frames.data?.length === 0 && <Empty>This project has no frames.</Empty>}
          <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="sm">
            {frames.data?.map((frame) => (
              <ImageCard
                key={frame.asset_id}
                item={referenceFromFrame(frame)}
                caption={
                  frame.scene_number !== null
                    ? `scene ${frame.scene_number}, ${frame.slot}`
                    : `frame ${frame.asset_id}`
                }
                actions={actions}
              />
            ))}
          </SimpleGrid>
        </>
      )}
    </Stack>
  );
}

// --- Saved voices ----------------------------------------------------------------------------

function VoicesSection() {
  const voices = useVoices();
  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Saved voices: a clean recording and its exact words. A Character lab character speaks in
        one of them.
      </Text>
      {voices.isLoading && <Loader size="sm" />}
      {voices.isError && <LoadError title="Could not load the voices" error={voices.error} />}
      {voices.data?.length === 0 && (
        <Empty>No saved voices yet. Save a speech as a voice in the Voice tab.</Empty>
      )}
      {voices.data?.map((voice) => (
        <Paper key={voice.id} withBorder p="xs" radius="md">
          <Stack gap={6}>
            <Group justify="space-between" wrap="nowrap">
              <Text size="sm" fw={600}>
                {voice.name}
              </Text>
              <Text size="xs" c="dimmed">
                {voice.duration_s.toFixed(2)} s
              </Text>
            </Group>
            <audio src={voice.url} controls preload="none" style={{ width: "100%" }} />
            <Text size="xs" c="dimmed" lineClamp={2} title={voice.transcript}>
              {voice.transcript}
            </Text>
          </Stack>
        </Paper>
      ))}
    </Stack>
  );
}

// --- Speech (Voice lab runs) -------------------------------------------------------------------

function SpeechSection({ actions }: { actions: LibraryActions }) {
  const runs = useVoiceLabRuns();
  const finished = (runs.data?.pages.flat() ?? []).filter((run) => run.url !== null);
  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Every finished speech the Voice lab and the Character lab made.
      </Text>
      {runs.isLoading && <Loader size="sm" />}
      {runs.isError && <LoadError title="Could not load the speeches" error={runs.error} />}
      {runs.data && finished.length === 0 && <Empty>No finished speeches yet.</Empty>}
      {finished.map((run) => (
        <Paper key={run.id} withBorder p="xs" radius="md">
          <Stack gap={6}>
            <Text size="sm" lineClamp={2} title={run.text}>
              {run.text}
            </Text>
            <Text size="xs" c="dimmed">
              {speechParamsLine(run)} · {formatDateTime(run.created_at)}
            </Text>
            {run.url !== null && (
              <audio src={run.url} controls preload="none" style={{ width: "100%" }} />
            )}
            <Group gap="xs">
              <Button size="compact-xs" variant="default" onClick={() => actions.loadSpeech(run)}>
                Load into Voice
              </Button>
            </Group>
          </Stack>
        </Paper>
      ))}
      <MoreButton query={runs} />
    </Stack>
  );
}

// --- Clips (Video lab runs) --------------------------------------------------------------------

function ClipsSection({ actions }: { actions: LibraryActions }) {
  const runs = useLabVideoRuns();
  const finished = (runs.data?.pages.flat() ?? []).filter((run) => run.url !== null);
  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Every finished clip the Video lab and the Character lab made.
      </Text>
      {runs.isLoading && <Loader size="sm" />}
      {runs.isError && <LoadError title="Could not load the clips" error={runs.error} />}
      {runs.data && finished.length === 0 && <Empty>No finished clips yet.</Empty>}
      {finished.map((run) => (
        <Paper key={run.id} withBorder p="xs" radius="md">
          <Stack gap={6}>
            <Group gap="xs">
              <Badge variant="light" color="gray">
                {run.video_model}
              </Badge>
              {isLipSyncRun(run) && (
                <Badge variant="light" color="grape">
                  lip-sync
                </Badge>
              )}
              {isReferenceRun(run) && (
                <Badge variant="light" color="violet">
                  reference
                </Badge>
              )}
              <Text size="xs" c="dimmed">
                {formatDateTime(run.created_at)}
              </Text>
            </Group>
            {run.url !== null && (
              <video
                src={run.url}
                controls
                preload="none"
                playsInline
                style={{ width: "100%", maxHeight: 280, background: "#000" }}
              />
            )}
            <Text size="xs" c="dimmed" lineClamp={2} title={run.prompt}>
              {run.prompt}
            </Text>
            {/* A lip-synced clip needs its speech, which the Video form does not have. A
                MiniMax H3 reference clip is loaded as the reference form. */}
            {!isLipSyncRun(run) && (
              <Group>
                <Button size="compact-xs" variant="default" onClick={() => actions.loadClip(run)}>
                  Load into Video
                </Button>
              </Group>
            )}
          </Stack>
        </Paper>
      ))}
      <MoreButton query={runs} />
    </Stack>
  );
}

/**
 * Everything the Lab holds in one place, available from every tab: the images, the saved
 * voices, the speeches and the clips. An image, a speech or a clip can be sent to the tab that
 * can use it.
 */
export function LabLibraryDrawer({ opened, onClose, actions }: LabLibraryDrawerProps) {
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="xl"
      title={
        <Title order={4} component="span">
          Library
        </Title>
      }
    >
      <Tabs defaultValue="images">
        <Tabs.List>
          <Tabs.Tab value="images">Images</Tabs.Tab>
          <Tabs.Tab value="voices">Voices</Tabs.Tab>
          <Tabs.Tab value="speech">Speech</Tabs.Tab>
          <Tabs.Tab value="clips">Clips</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="images" pt="md">
          <ImagesSection actions={actions} />
        </Tabs.Panel>
        <Tabs.Panel value="voices" pt="md">
          <VoicesSection />
        </Tabs.Panel>
        <Tabs.Panel value="speech" pt="md">
          <SpeechSection actions={actions} />
        </Tabs.Panel>
        <Tabs.Panel value="clips" pt="md">
          <ClipsSection actions={actions} />
        </Tabs.Panel>
      </Tabs>
    </Drawer>
  );
}
