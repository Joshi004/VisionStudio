import { useState } from "react";
import { Link } from "react-router";
import {
  Alert,
  Badge,
  Button,
  Group,
  List,
  Loader,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useChooseMusicDirection,
  useMusicBible,
  useMusicBibleVersion,
  useRunMusicBible,
  useSaveMusicBible,
  type MusicBibleOut,
  type MusicBibleState,
} from "../../api/musicBible";
import { isJobActive } from "../../api/polling";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { ReplaceManualModal } from "../story/ReplaceManualModal";
import { MusicBibleEditor } from "./MusicBibleEditor";

type MusicBiblePanelProps = {
  projectId: number;
  /** Whether the project has a saved story. The Music Bible is written from the saved text. */
  hasStory: boolean;
};

/**
 * The Music Bible stage: four directions, the one chosen and why, and the Bible written for it.
 * Run / Re-run writes all three; "Choose this direction" on another card writes only the Bible
 * again. When music is switched off for the project, the panel only says so.
 */
export function MusicBiblePanel({ projectId, hasStory }: MusicBiblePanelProps) {
  const { data, isLoading, isError, error } = useMusicBible(projectId);
  const run = useRunMusicBible(projectId);
  const choose = useChooseMusicDirection(projectId);
  const save = useSaveMusicBible(projectId);
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  // The version the user picked. Until they pick one, the newest is shown.
  const [picked, setPicked] = useState<number | null>(null);

  const latest = data?.latest ?? null;
  const shownVersion = picked ?? latest?.version ?? null;
  const viewingOlder = latest !== null && shownVersion !== latest.version;
  const olderVersion = useMusicBibleVersion(projectId, viewingOlder ? shownVersion : null);
  const shown = viewingOlder ? (olderVersion.data ?? null) : latest;

  const job = data?.job ?? null;
  const active = isJobActive(job);
  const musicOff = data !== undefined && !data.music_enabled;
  const blocked = data?.blocked_reason ?? null;

  const startRun = (confirmReplaceManual: boolean) => {
    // A new version is on its way: show it when it arrives.
    setPicked(null);
    run.mutate({ confirmReplaceManual });
  };

  const startChoose = (version: number, directionId: string) => {
    setPicked(null);
    choose.mutate({ version, directionId });
  };

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Title order={4}>Music Bible</Title>
              <Text size="sm" c="dimmed">
                The story's score, planned once: four directions, the one chosen and why, and the
                themes, arc and restraint the later music steps follow.
              </Text>
            </Stack>
            <Group gap="sm" align="flex-end">
              {data && data.versions.length > 1 && (
                <Select
                  aria-label="Version"
                  w={190}
                  allowDeselect={false}
                  data={data.versions.map((version, index) => ({
                    value: String(version.version),
                    label: `Version ${version.version}${index === 0 ? " (newest)" : ""}`,
                  }))}
                  value={shownVersion === null ? null : String(shownVersion)}
                  onChange={(value) => value !== null && setPicked(Number(value))}
                />
              )}
              <Button
                variant="default"
                onClick={() => {
                  save.reset();
                  setPicked(null);
                  setEditing(true);
                }}
                disabled={musicOff || editing || latest === null || active || blocked !== null}
              >
                Edit
              </Button>
              <Button
                onClick={() => (data?.needs_confirmation ? setConfirming(true) : startRun(false))}
                loading={run.isPending || active}
                disabled={
                  !hasStory || isLoading || isError || editing || musicOff || blocked !== null
                }
              >
                {latest ? "Re-run" : "Run"}
              </Button>
            </Group>
          </Group>

          {!hasStory && (
            <Text size="sm" c="dimmed">
              Save the story above first: the Music Bible is written from the saved text.
            </Text>
          )}
          {hasStory && !musicOff && blocked !== null && (
            <Text size="sm" c="dimmed">
              {blocked}
            </Text>
          )}
          {musicOff && (
            <Alert color="gray" title="Music is switched off">
              This project is made without music, so this step is skipped. Turn music on in the{" "}
              <Link to={`/projects/${projectId}/settings`}>project settings</Link> to plan it.
            </Alert>
          )}
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the Music Bible">
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title="Could not start the Music Bible">
              {describeError(run.error)}
            </Alert>
          )}
          {choose.isError && (
            <Alert color="red" title="Could not choose the direction">
              {describeError(choose.error)}
            </Alert>
          )}
          {job && job.status !== "succeeded" && <JobStatusBadge job={job} />}
          {job?.status === "failed" && (
            <Alert color="red" title="The last run failed">
              {job.error ?? "The job failed."}
            </Alert>
          )}
          {data?.out_of_date && !viewingOlder && !musicOff && (
            <Alert color="yellow" title="Out of date">
              <Stack gap={4}>
                <Text size="sm">
                  Something this version was written from has changed. Press Re-run to write a
                  new one.
                </Text>
                {data.reasons.length > 0 && (
                  <List size="sm">
                    {data.reasons.map((reason) => (
                      <List.Item key={reason}>{reason}</List.Item>
                    ))}
                  </List>
                )}
              </Stack>
            </Alert>
          )}
        </Stack>
      </Paper>

      {editing && latest && data && (
        <Paper withBorder p="md" radius="md">
          <MusicBibleEditor
            initial={latest.content}
            state={data}
            saving={save.isPending}
            error={save.error}
            onSave={(content) => save.mutate(content, { onSuccess: () => setEditing(false) })}
            onCancel={() => setEditing(false)}
          />
        </Paper>
      )}
      {shown && !editing && (
        <MusicBibleView
          bible={shown}
          scenes={data?.scenes ?? []}
          characters={data?.characters ?? []}
          places={data?.places ?? []}
          busy={active || choose.isPending}
          onChoose={(directionId) => startChoose(shown.version, directionId)}
        />
      )}
      {viewingOlder && olderVersion.isError && (
        <Alert color="red" title="Could not load the version">
          {describeError(olderVersion.error)}
        </Alert>
      )}
      <ReplaceManualModal
        opened={confirming}
        title="Run the Music Bible again?"
        what="The newest Music Bible (or its chosen direction)"
        confirmLabel="Re-run"
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          startRun(true);
        }}
      />
    </Stack>
  );
}

type MusicBibleViewProps = {
  bible: MusicBibleOut;
  scenes: MusicBibleState["scenes"];
  characters: MusicBibleState["characters"];
  places: MusicBibleState["places"];
  busy: boolean;
  onChoose: (directionId: string) => void;
};

function sourceLabel(source: string) {
  return source === "manual" ? "written by you" : "written by the model";
}

/** The four directions (the chosen one marked), then the Bible written for it. */
function MusicBibleView({
  bible,
  scenes,
  characters,
  places,
  busy,
  onChoose,
}: MusicBibleViewProps) {
  const { content, choice } = bible;
  const sceneTitle = (id: string) => scenes.find((scene) => scene.id === id)?.title ?? id;
  const refName = (kind: string, ref: string | null | undefined) => {
    const list = kind === "place" ? places : characters;
    return list.find((item) => item.id === ref)?.name ?? ref;
  };

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Group gap="sm">
            <Title order={5}>Four directions</Title>
            <Text size="xs" c="dimmed">
              Version {bible.version}, {sourceLabel(bible.source)}
            </Text>
          </Group>
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            {bible.directions.map((direction) => {
              const chosen = direction.id === choice.direction_id;
              return (
                <Paper
                  key={direction.id}
                  withBorder
                  p="sm"
                  radius="md"
                  style={chosen ? { borderColor: "var(--mantine-color-blue-6)" } : undefined}
                >
                  <Stack gap={6}>
                    <Group justify="space-between" wrap="nowrap">
                      <Text fw={600}>{direction.name}</Text>
                      {chosen && (
                        <Badge variant="light">
                          Chosen {choice.by === "owner" ? "by you" : "by the model"}
                        </Badge>
                      )}
                    </Group>
                    <Text size="sm">{direction.summary}</Text>
                    <Text size="xs" c="dimmed">
                      Instruments: {direction.instruments.join(", ")}
                    </Text>
                    <Text size="xs" c="dimmed">
                      Feel: {direction.feel}
                    </Text>
                    <Text size="xs" c="dimmed">
                      Different because: {direction.differs_by}
                    </Text>
                    {chosen ? (
                      <Text size="sm">{choice.reasons}</Text>
                    ) : (
                      <Group>
                        <Button
                          variant="default"
                          size="xs"
                          disabled={busy}
                          onClick={() => onChoose(direction.id)}
                        >
                          Choose this direction
                        </Button>
                      </Group>
                    )}
                  </Stack>
                </Paper>
              );
            })}
          </SimpleGrid>
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <Title order={5}>The Bible</Title>
          <Text size="sm">{content.concept}</Text>

          <Section title="Instruments">
            <Text size="sm">{content.sound_world.instruments.join(", ")}</Text>
          </Section>
          {content.sound_world.avoid.length > 0 && (
            <Section title="Avoid">
              <Text size="sm">{content.sound_world.avoid.join(", ")}</Text>
            </Section>
          )}
          <Section title="Musical feel">
            <Text size="sm">Tempo: {content.musical_feel.tempo}</Text>
            <Text size="sm">Mode: {content.musical_feel.mode_leaning}</Text>
            <Text size="sm">Density: {content.musical_feel.density}</Text>
          </Section>

          <Section title="Themes">
            {content.themes.map((theme) => (
              <Stack key={theme.id} gap={2}>
                <Group gap="xs">
                  <Text size="sm" fw={600}>
                    {theme.name}
                  </Text>
                  {theme.main && <Badge size="sm">Main theme</Badge>}
                </Group>
                <Text size="sm">
                  Stands for {theme.stands_for.kind}
                  {theme.stands_for.ref ? ` ${refName(theme.stands_for.kind, theme.stands_for.ref)}` : ""}
                  : {theme.stands_for.description}
                </Text>
                <Text size="xs" c="dimmed">
                  {theme.signature_instrument}
                  {theme.emotions.length > 0 ? `. Feels: ${theme.emotions.join(", ")}` : ""}
                </Text>
              </Stack>
            ))}
          </Section>

          <Section title="Arc">
            {content.arc.map((entry) => (
              <Text key={entry.scene_id} size="sm">
                <b>{sceneTitle(entry.scene_id)}:</b> {entry.music}
              </Text>
            ))}
          </Section>

          <Section title="Restraint">
            <Text size="sm">{content.restraint.amount}</Text>
            {content.restraint.silence_rules.length > 0 && (
              <List size="sm">
                {content.restraint.silence_rules.map((rule, index) => (
                  <List.Item key={index}>{rule}</List.Item>
                ))}
              </List>
            )}
          </Section>

          <Section title="Ambience signature">
            <Text size="sm">{content.ambience_signature}</Text>
          </Section>
        </Stack>
      </Paper>
    </Stack>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Stack gap={2}>
      <Text size="xs" fw={700} c="dimmed" tt="uppercase">
        {title}
      </Text>
      {children}
    </Stack>
  );
}
