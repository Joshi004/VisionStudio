import { useState } from "react";
import { Alert, Badge, Button, Group, List, Loader, Paper, Stack, Table, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useGraphicBriefs,
  useRunGraphicBrief,
  type GraphicBriefScene,
  type GraphicShot,
  type GraphicShotBrief,
} from "../../api/graphicBriefs";
import { isJobActive } from "../../api/polling";
import { KIND_LABELS, OP_LABELS } from "../graphicsLab/graphicsLabView";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { FeedbackBadge } from "./FeedbackBadge";
import { FeedbackModal } from "./FeedbackModal";

type GraphicBriefsPanelProps = {
  projectId: number;
};

const STATUS_BADGE: Record<GraphicShot["status"], { label: string; color: string }> = {
  none: { label: "No brief yet", color: "gray" },
  writing: { label: "Being written", color: "blue" },
  ready: { label: "Ready", color: "green" },
  failed: { label: "Failed", color: "red" },
  out_of_date: { label: "Out of date", color: "yellow" },
};

/** The note being written: which shot it is on. */
type Noting = { sceneId: string; shot: GraphicShot };

/**
 * The graphic briefs stage of a continuous explainer: for each graphic shot the cut planner
 * chose, one brief written from the shot's words and the sentences around them. A number on a
 * graphic must be said in those sentences; each part of it appears on a word of the shot.
 */
export function GraphicBriefsPanel({ projectId }: GraphicBriefsPanelProps) {
  const { data, isLoading, isError, error } = useGraphicBriefs(projectId);
  const run = useRunGraphicBrief(projectId);
  const [noting, setNoting] = useState<Noting | null>(null);

  const startRun = (sceneId: string, shot: GraphicShot, feedback?: string) =>
    run.mutate({ sceneId, shotId: shot.id, feedback });

  return (
    <Stack gap="sm">
      <Paper withBorder p="md" radius="md">
        <Stack gap="xs">
          <Title order={4}>Graphic briefs</Title>
          <Text size="sm" c="dimmed">
            Each graphic shot gets a brief: what it shows, the numbers it uses and the words each
            part appears on. A number must be said in the shot's words or in the sentences around
            them. The model writes it, one call for each shot.
          </Text>
          {isLoading && <Loader size="sm" />}
          {isError && (
            <Alert color="red" title="Could not load the graphic briefs">
              {describeError(error)}
            </Alert>
          )}
          {run.isError && (
            <Alert color="red" title="Could not start the graphic brief">
              {describeError(run.error)}
            </Alert>
          )}
          {data?.blocked_reason && (
            <Text size="sm" c="dimmed">
              {data.blocked_reason}
            </Text>
          )}
          {data?.wanted && data.scenes.length === 0 && (
            <Text size="sm" c="dimmed">
              No scene has a graphic shot yet. Graphic shots appear when the shots of a scene are
              planned.
            </Text>
          )}
        </Stack>
      </Paper>

      {data?.scenes.map((scene) => (
        <SceneBriefs
          key={scene.id}
          scene={scene}
          starting={run.isPending}
          onRun={(shot) => startRun(scene.id, shot)}
          onNote={(shot) => setNoting({ sceneId: scene.id, shot })}
        />
      ))}

      <FeedbackModal
        opened={noting !== null}
        title="Feedback on the graphic brief"
        what="the graphic brief"
        initialText={noting?.shot.brief?.feedback ?? ""}
        writtenByUser={false}
        submitLabel="Write with feedback"
        onCancel={() => setNoting(null)}
        onSubmit={(text) => {
          if (noting !== null) {
            startRun(noting.sceneId, noting.shot, text);
          }
          setNoting(null);
        }}
      />
    </Stack>
  );
}

type SceneBriefsProps = {
  scene: GraphicBriefScene;
  starting: boolean;
  onRun: (shot: GraphicShot) => void;
  onNote: (shot: GraphicShot) => void;
};

function SceneBriefs({ scene, starting, onRun, onNote }: SceneBriefsProps) {
  return (
    <Stack gap="xs">
      <Text fw={600}>{scene.index !== null ? `Scene ${scene.index}: ${scene.title}` : scene.title}</Text>
      {scene.shots.map((shot) => (
        <ShotBrief key={shot.id} shot={shot} starting={starting} onRun={onRun} onNote={onNote} />
      ))}
    </Stack>
  );
}

type ShotBriefProps = {
  shot: GraphicShot;
  starting: boolean;
  onRun: (shot: GraphicShot) => void;
  onNote: (shot: GraphicShot) => void;
};

function ShotBrief({ shot, starting, onRun, onNote }: ShotBriefProps) {
  const active = isJobActive(shot.job);
  const badge = STATUS_BADGE[shot.status];
  const hasBrief = shot.brief !== null;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={4}>
            <Group gap="xs">
              <Text size="sm" fw={600}>
                {shot.id.replace("shot_", "Shot ")}
              </Text>
              <Badge color={badge.color} variant="light">
                {badge.label}
              </Badge>
              {shot.brief && <FeedbackBadge text={shot.brief.feedback} />}
              <Text size="xs" c="dimmed">
                {shot.start_s.toFixed(1)} to {shot.end_s.toFixed(1)} s
              </Text>
            </Group>
            <ShotWords shot={shot} />
            <Text size="xs" c="dimmed">
              Planner's description: {shot.description}
            </Text>
          </Stack>
          <Group gap="xs">
            {hasBrief && (
              <Button
                size="compact-sm"
                variant="default"
                disabled={!shot.can_run || active || starting}
                onClick={() => onNote(shot)}
              >
                Write again with a note
              </Button>
            )}
            <Button
              size="compact-sm"
              loading={active || starting}
              disabled={!shot.can_run}
              onClick={() => onRun(shot)}
            >
              {hasBrief ? "Write again" : "Write the brief"}
            </Button>
          </Group>
        </Group>

        {!shot.can_run && !active && shot.blocked_reason !== null && (
          <Text size="xs" c="dimmed">
            {shot.blocked_reason}
          </Text>
        )}
        {shot.job && shot.job.status !== "succeeded" && <JobStatusBadge job={shot.job} />}
        {shot.last_error && (
          <Text size="sm" c="red" style={{ wordBreak: "break-word" }}>
            {shot.last_error}
          </Text>
        )}
        {shot.status === "out_of_date" && (
          <Alert color="yellow" title="Out of date">
            <Stack gap={4}>
              <Text size="sm">
                Something this brief was written from has changed. Press Write again to make a new
                one.
              </Text>
              {shot.reasons.length > 0 && (
                <List size="sm">
                  {shot.reasons.map((reason) => (
                    <List.Item key={reason}>{reason}</List.Item>
                  ))}
                </List>
              )}
            </Stack>
          </Alert>
        )}

        {shot.brief && <BriefDetails brief={shot.brief} />}
      </Stack>
    </Paper>
  );
}

/** The shot's words, with the sentences around them dimmed: numbers may come from those too. */
function ShotWords({ shot }: { shot: GraphicShot }) {
  return (
    <Text size="sm" style={{ wordBreak: "break-word" }}>
      {shot.words_before && (
        <Text span c="dimmed">
          {shot.words_before}{" "}
        </Text>
      )}
      <Text span fw={600}>
        {shot.spoken_text}
      </Text>
      {shot.words_after && (
        <Text span c="dimmed">
          {" "}
          {shot.words_after}
        </Text>
      )}
    </Text>
  );
}

function factText(fact: GraphicShotBrief["content"]["facts"][number]): string {
  const scale = fact.scale === "none" ? "" : ` ${fact.scale}`;
  const unit = fact.unit === "none" ? "" : ` ${fact.unit}`;
  return `${fact.value}${scale}${unit}`;
}

function BriefDetails({ brief }: { brief: GraphicShotBrief }) {
  const { content } = brief;
  return (
    <Stack gap="md">
      <Group gap="xs">
        <Badge variant="light">{KIND_LABELS[content.kind]}</Badge>
        <Text size="xs" c="dimmed">
          Version {brief.version}, written by the model.
        </Text>
      </Group>

      <Stack gap={2}>
        <Text size="sm" fw={600}>
          {content.intent}
        </Text>
        <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {content.visual_brief}
        </Text>
      </Stack>

      {content.facts.length > 0 || content.derived.length > 0 ? (
        <Table.ScrollContainer minWidth={420}>
          <Table withTableBorder verticalSpacing={4} fz="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Id</Table.Th>
                <Table.Th>Number</Table.Th>
                <Table.Th>Value</Table.Th>
                <Table.Th>Where it comes from</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {content.facts.map((fact) => (
                <Table.Tr key={fact.id}>
                  <Table.Td>{fact.id}</Table.Td>
                  <Table.Td>{fact.label}</Table.Td>
                  <Table.Td fw={600}>{factText(fact)}</Table.Td>
                  <Table.Td>said as &ldquo;{fact.said_as}&rdquo;</Table.Td>
                </Table.Tr>
              ))}
              {content.derived.map((item) => (
                <Table.Tr key={item.id}>
                  <Table.Td>{item.id}</Table.Td>
                  <Table.Td>{item.label}</Table.Td>
                  <Table.Td>worked out by code</Table.Td>
                  <Table.Td>
                    {OP_LABELS[item.op]} of {item.of.join(", ")}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      ) : (
        <Text size="xs" c="dimmed">
          No numbers: the graphic shows no figures.
        </Text>
      )}

      <Table.ScrollContainer minWidth={420}>
        <Table withTableBorder verticalSpacing={4} fz="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Beat</Table.Th>
              <Table.Th>At</Table.Th>
              <Table.Th>When the shot says</Table.Th>
              <Table.Th>What appears</Table.Th>
              <Table.Th>Shows</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {content.beats.map((beat) => (
              <Table.Tr key={beat.id}>
                <Table.Td>{beat.id}</Table.Td>
                <Table.Td>{beat.at_s !== null ? `${beat.at_s.toFixed(1)} s` : "?"}</Table.Td>
                <Table.Td>&ldquo;{beat.phrase}&rdquo;</Table.Td>
                <Table.Td>{beat.shows}</Table.Td>
                <Table.Td>{beat.refs.join(", ")}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  );
}
