import { useState, type Dispatch, type SetStateAction } from "react";
import { Alert, Button, FileInput, Group, Select, SegmentedControl, SimpleGrid, Stack, Text, TextInput, Textarea } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  SOURCE_UPLOAD_MAX_MB,
  useCreateMusicEdits,
  useJoinMusicSources,
  useMusicLabRuns,
  useMusicSources,
  useUploadMusicSource,
  type MusicCatalog,
  type MusicSource,
} from "../../api/musicLab";
import { FieldInput } from "./MusicModelFields";
import {
  editModelOf,
  editProblem,
  runNumberOf,
  savedSourceLabel,
  secondsText,
  sourceInfoOf,
  toEditRequest,
  type MusicEditFormState,
  type SourceInfo,
  type SourceMode,
} from "./musicEditView";
import { KIND_HELP, MAX_VARIANTS, emptyValues, type FieldValue } from "./musicLabView";

type MusicEditPanelProps = {
  /** The form lives in the Lab page, so changing tabs never loses what was typed. */
  state: MusicEditFormState;
  onChange: Dispatch<SetStateAction<MusicEditFormState>>;
  catalog: MusicCatalog;
};

/** Stores a recording from the computer as a source to edit. */
function UploadSource({ onDone }: { onDone: (source: MusicSource) => void }) {
  const upload = useUploadMusicSource();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");

  return (
    <Stack gap="xs">
      <FileInput
        label="Recording"
        description={`WAV, MP3, M4A or FLAC, up to ${SOURCE_UPLOAD_MAX_MB} MB.`}
        accept="audio/*,.wav,.mp3,.m4a,.flac"
        value={file}
        onChange={setFile}
        clearable
      />
      <TextInput
        label="Name"
        description="Empty: the name of the file."
        value={name}
        onChange={(event) => setName(event.currentTarget.value)}
        maxLength={80}
      />
      <Group>
        <Button
          size="compact-sm"
          variant="light"
          disabled={file === null}
          loading={upload.isPending}
          onClick={() => {
            if (file !== null) {
              upload.mutate({ file, name: name.trim() === "" ? file.name : name.trim() }, { onSuccess: onDone });
            }
          }}
        >
          Upload
        </Button>
      </Group>
      {upload.isError && (
        <Text size="xs" c="red">
          {describeError(upload.error)}
        </Text>
      )}
    </Stack>
  );
}

/** Joins two finished runs into one source, with a silence between them and after them. */
function JoinSource({ onDone }: { onDone: (source: MusicSource) => void }) {
  const join = useJoinMusicSources();
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  const [gap, setGap] = useState("0");
  const [tail, setTail] = useState("0");

  const firstId = /^\d{1,9}$/.test(first.trim()) ? Number(first) : null;
  const secondId = /^\d{1,9}$/.test(second.trim()) ? Number(second) : null;
  const gapS = /^\d+(\.\d+)?$/.test(gap.trim()) ? Number(gap) : null;
  const tailS = /^\d+(\.\d+)?$/.test(tail.trim()) ? Number(tail) : null;
  const ready = firstId !== null && secondId !== null && gapS !== null && tailS !== null;

  return (
    <Stack gap="xs">
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <TextInput
          label="First run (number)"
          value={first}
          onChange={(event) => setFirst(event.currentTarget.value)}
        />
        <TextInput
          label="Second run (number)"
          value={second}
          onChange={(event) => setSecond(event.currentTarget.value)}
        />
        <TextInput
          label="Silence between them (s)"
          value={gap}
          onChange={(event) => setGap(event.currentTarget.value)}
        />
        <TextInput
          label="Silence after them (s)"
          description="Room for a model to continue the sound past its end."
          value={tail}
          onChange={(event) => setTail(event.currentTarget.value)}
        />
      </SimpleGrid>
      <Group>
        <Button
          size="compact-sm"
          variant="light"
          disabled={!ready}
          loading={join.isPending}
          onClick={() => {
            if (ready) {
              join.mutate({ run_ids: [firstId, secondId], gap_s: gapS, tail_s: tailS, crossfade_s: 0 }, { onSuccess: onDone });
            }
          }}
        >
          Join
        </Button>
      </Group>
      {join.isError && (
        <Text size="xs" c="red">
          {describeError(join.error)}
        </Text>
      )}
    </Stack>
  );
}

/**
 * Editing a sound the lab already made or one you bring: choose the source, what to do with it
 * (repaint a window, make a cover, inpaint or extend, or transform), and the settings of that
 * operation. Each edit is a paid GPU job and shows below, on the runs list, with its source.
 */
export function MusicEditPanel({ state, onChange, catalog }: MusicEditPanelProps) {
  const runs = useMusicLabRuns();
  const sources = useMusicSources();
  const create = useCreateMusicEdits();

  const operation = catalog.operations.find((entry) => entry.id === state.operation);
  const model = editModelOf(catalog, state);

  function update(changes: Partial<MusicEditFormState>) {
    onChange((current) => ({ ...current, ...changes }));
  }

  function chooseSource(chosen: MusicSource) {
    update({ sourceMode: "saved", sourceId: chosen.id });
  }

  // What is known of the source, so the form can warn about a source that is too long.
  let source: SourceInfo | null = null;
  if (state.sourceMode === "run") {
    const run = runs.data?.pages.flat().find((entry) => entry.id === runNumberOf(state));
    if (run !== undefined) {
      source = { label: `Run ${run.id}`, url: run.url, durationS: run.duration_s, seamS: null };
    }
  } else {
    const saved = sources.data?.find((entry) => entry.id === state.sourceId);
    source = saved === undefined ? null : sourceInfoOf(saved);
  }

  const problem = editProblem(state, catalog, source);
  const values = model === null ? {} : { ...emptyValues(model), ...state.values };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (problem === null) {
          create.mutate(toEditRequest(state, catalog));
        }
      }}
    >
      <Stack gap="md">
        <Stack gap={2}>
          <Text size="sm" fw={600}>
            Edit a sound
          </Text>
          <Text size="xs" c="dimmed">
            Change part of a sound, make a cover of it, extend it, or transform it. The source is a
            run above, a recording you upload, or two runs joined. Each edit is a paid GPU job and
            appears in the runs below.
          </Text>
        </Stack>

        <Stack gap="xs">
          <Text size="sm" fw={500}>
            Source
          </Text>
          <SegmentedControl
            value={state.sourceMode}
            onChange={(value) => update({ sourceMode: value as SourceMode })}
            data={[
              { value: "run", label: "A run" },
              { value: "saved", label: "A recording or a join" },
            ]}
          />
          {state.sourceMode === "run" ? (
            <TextInput
              label="Run number"
              description="The number on the run's card. Press “Edit this run” on a card to fill it."
              value={state.runNumber}
              onChange={(event) => update({ runNumber: event.currentTarget.value })}
            />
          ) : (
            <Stack gap="xs">
              <Select
                label="Saved source"
                data={(sources.data ?? []).map((entry) => ({
                  value: String(entry.id),
                  label: savedSourceLabel(entry),
                }))}
                value={state.sourceId === null ? null : String(state.sourceId)}
                onChange={(value) => update({ sourceId: value === null ? null : Number(value) })}
                placeholder={sources.isLoading ? "Loading…" : "Choose one, or upload or join below"}
                nothingFoundMessage="Nothing saved yet."
                clearable
              />
              <details>
                <summary style={{ cursor: "pointer", fontSize: "var(--mantine-font-size-xs)" }}>
                  Upload a recording
                </summary>
                <UploadSource onDone={chooseSource} />
              </details>
              <details>
                <summary style={{ cursor: "pointer", fontSize: "var(--mantine-font-size-xs)" }}>
                  Join two runs
                </summary>
                <JoinSource onDone={chooseSource} />
              </details>
              {sources.isError && (
                <Text size="xs" c="red">
                  {describeError(sources.error)}
                </Text>
              )}
            </Stack>
          )}
          {source !== null && (
            <Stack gap={2}>
              {source.url !== null && (
                <audio controls preload="none" src={source.url} style={{ width: "100%" }} />
              )}
              <Text size="xs" c="dimmed">
                {source.label}
                {source.durationS !== null && ` · ${secondsText(source.durationS)}`}
                {source.seamS !== null && ` · the runs meet at ${secondsText(source.seamS)}`}
              </Text>
            </Stack>
          )}
        </Stack>

        <Stack gap="xs">
          <Select
            label="What to do"
            description={operation?.help}
            data={catalog.operations.map((entry) => ({ value: entry.id, label: entry.label }))}
            value={state.operation}
            onChange={(value) => {
              const next = catalog.operations.find((entry) => entry.id === value);
              if (next !== undefined) {
                update({ operation: next.id });
              }
            }}
            allowDeselect={false}
          />
          {operation !== undefined && operation.models.length > 1 && (
            <Select
              label="Model"
              data={operation.models.map((entry) => ({ value: entry.model, label: entry.label }))}
              value={model?.model ?? null}
              onChange={(value) => {
                const next = operation.models.find((entry) => entry.model === value);
                if (next !== undefined) {
                  update({ model: next.model });
                }
              }}
              allowDeselect={false}
            />
          )}
          {model !== null && (
            <Text size="xs" c="dimmed">
              {model.label} edits at most {model.max_source_s} s of sound.
            </Text>
          )}
        </Stack>

        {model !== null && (
          <Stack gap="sm">
            {model.fields.map((spec) => (
              <FieldInput
                key={`${model.model}.${spec.name}`}
                model={model.model}
                spec={spec}
                value={values[spec.name] ?? (spec.type === "flag" ? false : "")}
                onChange={(value: FieldValue) =>
                  onChange((current) => ({ ...current, values: { ...current.values, [spec.name]: value } }))
                }
              />
            ))}
          </Stack>
        )}

        <Stack gap="xs">
          <Select
            label="Kind of sound"
            description={KIND_HELP[state.kind]}
            data={catalog.kinds.map((entry) => ({ value: entry.id, label: entry.label }))}
            value={state.kind}
            onChange={(value) => {
              const next = catalog.kinds.find((entry) => entry.id === value);
              if (next !== undefined) {
                update({ kind: next.id });
              }
            }}
            allowDeselect={false}
          />
          <Textarea
            label="What you want from the edit"
            description="In your own words. It is kept on the runs it makes."
            value={state.description}
            onChange={(event) => update({ description: event.currentTarget.value })}
            autosize
            minRows={2}
          />
        </Stack>

        <Group align="flex-start" grow>
          <TextInput
            label="Variants"
            description={`How many seeds to try, from 1 to ${MAX_VARIANTS}.`}
            value={state.variants}
            onChange={(event) => update({ variants: event.currentTarget.value })}
          />
          <TextInput
            label="Seed"
            description="Empty: random."
            value={state.seed}
            onChange={(event) => update({ seed: event.currentTarget.value })}
          />
        </Group>

        <Stack gap={4} align="flex-start">
          <Button type="submit" loading={create.isPending} disabled={problem !== null}>
            Make the edit
          </Button>
          {problem !== null && (
            <Text size="xs" c="dimmed">
              {problem}
            </Text>
          )}
        </Stack>

        {create.isError && (
          <Alert color="red" title="The edit was not started">
            {describeError(create.error)}
          </Alert>
        )}
        {create.isSuccess && (
          <Alert color="green" title="Started">
            {create.data.length === 1 ? "The edit is" : `${create.data.length} edits are`} waiting
            for a free GPU slot and will appear below. You can leave this page: it keeps going.
          </Alert>
        )}
      </Stack>
    </form>
  );
}
