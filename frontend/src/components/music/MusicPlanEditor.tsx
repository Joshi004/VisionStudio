import { useMemo, useState } from "react";
import {
  Button,
  Group,
  NumberInput,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import type {
  MusicPlanAnchorInput,
  MusicPlanCueInput,
  MusicPlanInput,
  MusicPlanState,
  MusicPlanTimeline,
} from "../../api/musicPlan";
import { EditorActions } from "../story/editorParts";
import {
  END_STYLE_LABELS,
  JOIN_LABELS,
  KIND_LABELS,
  MAKER_LABELS,
  RELATION_LABELS,
  START_STYLE_LABELS,
  anchorSeconds,
  formatSeconds,
  refLabel,
  shorten,
} from "./musicPlanView";

type MusicPlanEditorProps = {
  /** The newest plan; the form starts from it. */
  initial: NonNullable<MusicPlanState["latest"]>["content"];
  timeline: MusicPlanTimeline;
  themes: MusicPlanState["themes"];
  saving: boolean;
  error: unknown;
  onSave: (content: MusicPlanInput) => void;
  onCancel: () => void;
};

type BoundaryDraft = { join: string; reason: string };

/** Score and ambience beds are lanes: neighbours in a lane need a join. */
const LANE_KINDS = ["score", "bed"];
const SPAN_KINDS = ["score", "bed", "silence"];

function toOptions(labels: Record<string, string>) {
  return Object.entries(labels).map(([value, label]) => ({ value, label }));
}

const KIND_OPTIONS = toOptions(KIND_LABELS);
const RELATION_OPTIONS = toOptions(RELATION_LABELS);
const JOIN_OPTIONS = toOptions(JOIN_LABELS);
const START_STYLE_OPTIONS = toOptions(START_STYLE_LABELS);
const END_STYLE_OPTIONS = toOptions(END_STYLE_LABELS);
const POINT_MAKER_OPTIONS = [
  { value: "stable_audio_3", label: MAKER_LABELS.stable_audio_3 },
  { value: "h3", label: MAKER_LABELS.h3 },
];
const EDGE_OPTIONS = [
  { value: "start", label: "start" },
  { value: "end", label: "end" },
];
const STRICT_OPTIONS = [
  { value: "loose", label: "loose" },
  { value: "tight", label: "tight" },
];

const boundaryKey = (from: string, to: string) => `${from}>${to}`;

/** Where a cue starts, in nominal seconds, to put the cues in time order. */
function startOf(timeline: MusicPlanTimeline, cue: MusicPlanCueInput): number {
  const anchor = cue.start ?? cue.at;
  return (anchor && anchorSeconds(timeline, anchor)) || 0;
}

/**
 * The music plan as a form. Each cue is a card: what it is, where it sits (anchors picked from the
 * story's own scenes, shots, lines and events), and its wording. Neighbouring score cues, and
 * neighbouring ambience beds, get a join. The server checks everything again against the story
 * as it is now (references, themes, overlaps, joins) and says which cue is wrong. Cue ids are
 * renumbered in time order when it saves.
 */
export function MusicPlanEditor({
  initial,
  timeline,
  themes,
  saving,
  error,
  onSave,
  onCancel,
}: MusicPlanEditorProps) {
  // Only the fields that can be written: the server refuses a field it does not know.
  const [cues, setCues] = useState<MusicPlanCueInput[]>(() =>
    initial.cues.map((cue) => ({
      id: cue.id,
      kind: cue.kind,
      summary: cue.summary,
      purpose: cue.purpose,
      reason: cue.reason,
      intensity: cue.intensity,
      theme_id: cue.theme_id,
      emotion: cue.emotion,
      maker: cue.kind === "point" ? cue.maker : null,
      start: cue.start && toAnchor(cue.start),
      end: cue.end && toAnchor(cue.end),
      at: cue.at && toAnchor(cue.at),
      start_style: cue.start_style,
      end_style: cue.end_style,
      sound_request: cue.sound_request && { ...cue.sound_request },
    })),
  );
  const [boundaries, setBoundaries] = useState<Record<string, BoundaryDraft>>(() =>
    Object.fromEntries(
      initial.boundaries.map((item) => [
        boundaryKey(item.from_cue, item.to_cue),
        { join: item.join, reason: item.reason },
      ]),
    ),
  );
  const [counter, setCounter] = useState(1);

  const anchorOptions = useMemo(() => buildAnchorOptions(timeline), [timeline]);
  const themeOptions = themes.map((theme) => ({ value: theme.id, label: theme.name }));
  const soundEvents = timeline.events.filter((event) => event.type === "sound_event");

  const sorted = useMemo(
    () =>
      cues
        .map((cue, index) => ({ cue, index }))
        .sort((a, b) => startOf(timeline, a.cue) - startOf(timeline, b.cue) || a.index - b.index)
        .map((item) => item.cue),
    [cues, timeline],
  );
  /** The neighbouring pairs of each lane, in time order, and the cue they are between. */
  const pairs = useMemo(
    () =>
      LANE_KINDS.flatMap((kind) => {
        const lane = sorted.filter((cue) => cue.kind === kind);
        return lane.slice(1).map((later, index) => ({ from: lane[index], to: later }));
      }),
    [sorted],
  );

  const changeCue = (id: string, part: Partial<MusicPlanCueInput>) =>
    setCues(cues.map((cue) => (cue.id === id ? { ...cue, ...part } : cue)));

  const changeKind = (cue: MusicPlanCueInput, kind: string) => {
    const first = defaultAnchor(timeline);
    const spans = SPAN_KINDS.includes(kind);
    changeCue(cue.id, {
      kind,
      start: spans ? (cue.start ?? cue.at ?? first) : null,
      end: spans ? (cue.end ?? cue.at ?? first) : null,
      at: spans ? null : (cue.at ?? cue.start ?? first),
      maker: kind === "point" ? (cue.maker ?? "stable_audio_3") : null,
      sound_request: kind === "point" ? cue.sound_request : null,
      theme_id: kind === "score" ? cue.theme_id : null,
      emotion: kind === "score" ? cue.emotion : null,
      start_style: LANE_KINDS.includes(kind) ? (cue.start_style ?? "fade_in") : null,
      end_style: LANE_KINDS.includes(kind) ? (cue.end_style ?? "fade_out") : null,
    });
  };

  const addCue = () => {
    const first = defaultAnchor(timeline);
    setCues([
      ...cues,
      {
        id: `new_${counter}`,
        kind: "score",
        summary: "",
        purpose: "",
        reason: "",
        intensity: 3,
        theme_id: null,
        emotion: null,
        maker: null,
        start: first,
        end: { ...first, edge: "end" },
        at: null,
        start_style: "fade_in",
        end_style: "fade_out",
        sound_request: null,
      },
    ]);
    setCounter(counter + 1);
  };

  const save = () =>
    onSave({
      cues: sorted.map((cue) => ({
        ...cue,
        sound_request: cue.kind === "point" && cue.maker === "h3" ? cue.sound_request : null,
      })),
      boundaries: pairs.map(({ from, to }) => {
        const draft = boundaries[boundaryKey(from.id, to.id)];
        return {
          from_cue: from.id,
          to_cue: to.id,
          join: draft?.join ?? "crossfade",
          reason: draft?.reason ?? "",
        };
      }),
    });

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        Edit the cues the model wrote, or add your own. Every cue needs its summary, purpose and
        reason. Where two score cues (or two beds) meet, say how they join.
      </Text>

      {sorted.map((cue) => (
        <Paper key={cue.id} withBorder p="sm" radius="md">
          <Stack gap="xs">
            <Group justify="space-between">
              <Text fw={600} size="sm">
                {cue.id.startsWith("new_") ? "New cue" : cue.id}
              </Text>
              <Button
                variant="default"
                size="xs"
                aria-label={`Remove ${cue.id}`}
                onClick={() => setCues(cues.filter((item) => item.id !== cue.id))}
              >
                Remove
              </Button>
            </Group>
            <SimpleGrid cols={{ base: 1, md: 3 }}>
              <Select
                label="Kind"
                allowDeselect={false}
                data={KIND_OPTIONS}
                value={cue.kind}
                onChange={(value) => value !== null && changeKind(cue, value)}
              />
              <NumberInput
                label="Intensity (1 to 5)"
                min={1}
                max={5}
                allowDecimal={false}
                value={cue.intensity}
                onChange={(value) =>
                  changeCue(cue.id, { intensity: typeof value === "number" ? value : 3 })
                }
              />
              {cue.kind === "point" && (
                <Select
                  label="Made by"
                  allowDeselect={false}
                  data={POINT_MAKER_OPTIONS}
                  value={cue.maker ?? "stable_audio_3"}
                  onChange={(value) => changeCue(cue.id, { maker: value })}
                />
              )}
              {cue.kind === "score" && (
                <Select
                  label="Theme"
                  clearable
                  placeholder="No theme"
                  data={themeOptions}
                  value={cue.theme_id ?? null}
                  onChange={(value) => changeCue(cue.id, { theme_id: value })}
                />
              )}
            </SimpleGrid>

            {cue.kind === "score" && (
              <TextInput
                label="Emotion"
                value={cue.emotion ?? ""}
                onChange={(event) => changeCue(cue.id, { emotion: event.currentTarget.value })}
              />
            )}
            <TextInput
              label="Summary"
              value={cue.summary}
              onChange={(event) => changeCue(cue.id, { summary: event.currentTarget.value })}
            />
            <TextInput
              label="Purpose"
              value={cue.purpose}
              onChange={(event) => changeCue(cue.id, { purpose: event.currentTarget.value })}
            />
            <Textarea
              label="Reason"
              autosize
              minRows={1}
              value={cue.reason}
              onChange={(event) => changeCue(cue.id, { reason: event.currentTarget.value })}
            />

            {SPAN_KINDS.includes(cue.kind) ? (
              <>
                <AnchorField
                  label="Starts"
                  anchor={cue.start ?? null}
                  timeline={timeline}
                  options={anchorOptions}
                  onChange={(anchor) => changeCue(cue.id, { start: anchor })}
                />
                <AnchorField
                  label="Ends"
                  anchor={cue.end ?? null}
                  timeline={timeline}
                  options={anchorOptions}
                  onChange={(anchor) => changeCue(cue.id, { end: anchor })}
                />
              </>
            ) : (
              <AnchorField
                label="At"
                anchor={cue.at ?? null}
                timeline={timeline}
                options={anchorOptions}
                onChange={(anchor) => changeCue(cue.id, { at: anchor })}
              />
            )}

            {LANE_KINDS.includes(cue.kind) && (
              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <Select
                  label="Start style"
                  description="Used where no earlier cue joins into this one."
                  allowDeselect={false}
                  data={START_STYLE_OPTIONS}
                  value={cue.start_style ?? "fade_in"}
                  onChange={(value) => changeCue(cue.id, { start_style: value })}
                />
                <Select
                  label="End style"
                  description="Used where no later cue joins out of this one."
                  allowDeselect={false}
                  data={END_STYLE_OPTIONS}
                  value={cue.end_style ?? "fade_out"}
                  onChange={(value) => changeCue(cue.id, { end_style: value })}
                />
              </SimpleGrid>
            )}

            {cue.kind === "point" && cue.maker === "h3" && (
              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <Select
                  label="Sound event"
                  description="Only a sound event the shot already carries can be made by H3."
                  placeholder="Pick a sound event"
                  searchable
                  data={soundEvents.map((event) => ({
                    value: event.ref,
                    label: refLabel(timeline, event.ref),
                  }))}
                  value={cue.sound_request?.event ?? null}
                  onChange={(value) =>
                    changeCue(cue.id, {
                      sound_request: value
                        ? { event: value, shot: soundShot(timeline, value) }
                        : null,
                    })
                  }
                />
              </SimpleGrid>
            )}
          </Stack>
        </Paper>
      ))}

      <Group>
        <Button variant="default" size="xs" onClick={addCue}>
          Add a cue
        </Button>
      </Group>

      {pairs.length > 0 && (
        <Stack gap="xs">
          <Text size="sm" fw={500}>
            Joins
          </Text>
          {pairs.map(({ from, to }) => {
            const key = boundaryKey(from.id, to.id);
            const draft = boundaries[key] ?? { join: "crossfade", reason: "" };
            const change = (part: Partial<BoundaryDraft>) =>
              setBoundaries({ ...boundaries, [key]: { ...draft, ...part } });
            return (
              <Paper key={key} withBorder p="sm" radius="md">
                <Stack gap="xs">
                  <Text size="sm">
                    {KIND_LABELS[from.kind]}: {shorten(from.summary || from.id, 40)} to{" "}
                    {shorten(to.summary || to.id, 40)}
                  </Text>
                  <Group align="flex-end" wrap="nowrap">
                    <Select
                      label="Join"
                      allowDeselect={false}
                      data={JOIN_OPTIONS}
                      value={draft.join}
                      onChange={(value) => value !== null && change({ join: value })}
                    />
                    <TextInput
                      label="Reason"
                      style={{ flex: 1 }}
                      value={draft.reason}
                      onChange={(event) => change({ reason: event.currentTarget.value })}
                    />
                  </Group>
                </Stack>
              </Paper>
            );
          })}
        </Stack>
      )}

      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the music plan"
        canSave={cues.length > 0}
        onSave={save}
        onCancel={onCancel}
      />
    </Stack>
  );
}

function toAnchor(anchor: MusicPlanAnchorInput): MusicPlanAnchorInput {
  return {
    ref: anchor.ref,
    edge: anchor.edge,
    relation: anchor.relation,
    strict: anchor.strict,
  };
}

function defaultAnchor(timeline: MusicPlanTimeline): MusicPlanAnchorInput {
  return { ref: timeline.scenes[0]?.ref ?? "", edge: "start", relation: "on", strict: "loose" };
}

/** The shot a sound event is heard in: the event names its shots, the first is used. */
function soundShot(timeline: MusicPlanTimeline, eventRef: string): string {
  return timeline.events.find((event) => event.ref === eventRef)?.shots[0] ?? "";
}

function buildAnchorOptions(timeline: MusicPlanTimeline) {
  const time = (start: number) => formatSeconds(start);
  return [
    {
      group: "Scenes",
      items: timeline.scenes.map((item) => ({
        value: item.ref,
        label: `${refLabel(timeline, item.ref)} (${time(item.start_s)})`,
      })),
    },
    {
      group: "Shots",
      items: timeline.shots.map((item) => ({
        value: item.ref,
        label: `${refLabel(timeline, item.ref)} (${time(item.start_s)})`,
      })),
    },
    {
      group: "Lines",
      items: timeline.units.map((item) => ({
        value: item.ref,
        label: `${refLabel(timeline, item.ref)} (${time(item.start_s)})`,
      })),
    },
    {
      group: "Events",
      items: timeline.events.map((item) => ({
        value: item.ref,
        label: `${refLabel(timeline, item.ref)} (${time(item.start_s)})`,
      })),
    },
  ];
}

type AnchorFieldProps = {
  label: string;
  anchor: MusicPlanAnchorInput | null;
  timeline: MusicPlanTimeline;
  options: ReturnType<typeof buildAnchorOptions>;
  onChange: (anchor: MusicPlanAnchorInput) => void;
};

/** One anchor: how it sits against which edge of which part of the story. */
function AnchorField({ label, anchor, timeline, options, onChange }: AnchorFieldProps) {
  const value = anchor ?? defaultAnchor(timeline);
  const seconds = anchorSeconds(timeline, value);
  const change = (part: Partial<MusicPlanAnchorInput>) => onChange({ ...value, ...part });
  return (
    <Stack gap={2}>
      <Text size="sm" fw={500}>
        {label}
        {seconds !== null && (
          <Text span size="xs" c="dimmed">
            {" "}
            (about {formatSeconds(seconds)})
          </Text>
        )}
      </Text>
      <SimpleGrid cols={{ base: 1, md: 4 }}>
        <Select
          aria-label={`${label}: relation`}
          allowDeselect={false}
          data={RELATION_OPTIONS}
          value={value.relation}
          onChange={(next) => next !== null && change({ relation: next })}
        />
        <Select
          aria-label={`${label}: edge`}
          allowDeselect={false}
          data={EDGE_OPTIONS}
          value={value.edge}
          onChange={(next) => next !== null && change({ edge: next })}
        />
        <Select
          aria-label={`${label}: how exact`}
          allowDeselect={false}
          data={STRICT_OPTIONS}
          value={value.strict}
          onChange={(next) => next !== null && change({ strict: next })}
        />
        <Select
          aria-label={`${label}: part of the story`}
          searchable
          allowDeselect={false}
          data={options}
          value={value.ref || null}
          onChange={(next) => next !== null && change({ ref: next })}
        />
      </SimpleGrid>
    </Stack>
  );
}
