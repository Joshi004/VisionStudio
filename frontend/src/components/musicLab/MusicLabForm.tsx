import {
  Button,
  Checkbox,
  Group,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import type { MusicCatalog, MusicModel } from "../../api/musicLab";
import { LicenseBadge } from "./MusicLicense";
import { MusicModelFields } from "./MusicModelFields";
import {
  boxesFor,
  formProblem,
  KIND_HELP,
  MAX_VARIANTS,
  selectedModels,
  takesUnderNarration,
  valuesFromFields,
  valuesOf,
  type MusicBriefState,
  type MusicLabFormState,
} from "./musicLabView";

type MusicLabFormProps = {
  state: MusicLabFormState;
  onChange: (state: MusicLabFormState) => void;
  catalog: MusicCatalog;
  onRun: () => void;
  running: boolean;
  /** Starts the job that writes the fields of these models from the brief. */
  onWrite: (models: MusicModel[]) => void;
  /** The models whose prompt-writing job is being sent. */
  starting: MusicModel[];
};

/**
 * The Music lab's form: the kind of sound, the brief (each box named after the pipeline stage
 * that will fill it), the models to compare with their licence warnings, the fields each model
 * will be sent, and the number of variants and the seed.
 */
export function MusicLabForm({ state, onChange, catalog, onRun, running, onWrite, starting }: MusicLabFormProps) {
  const problem = formProblem(state, catalog);
  const kind = catalog.kinds.find((entry) => entry.id === state.kind);
  const kindModels = catalog.models.filter((info) => kind?.models.includes(info.id));
  const chosen = selectedModels(state, catalog);
  const briefReady = state.brief.description.trim() !== "";

  function update(changes: Partial<MusicLabFormState>) {
    onChange({ ...state, ...changes });
  }

  function updateBrief(changes: Partial<MusicBriefState>) {
    update({ brief: { ...state.brief, ...changes } });
  }

  function chooseKind(id: string) {
    const next = catalog.kinds.find((entry) => entry.id === id);
    if (next !== undefined) {
      // Every model of the kind is chosen at first: the point of the lab is to compare them.
      update({ kind: next.id, selected: null });
    }
  }

  function toggleModel(id: MusicModel, checked: boolean) {
    const current = chosen.map((info) => info.id);
    update({ selected: checked ? [...current, id] : current.filter((entry) => entry !== id) });
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (problem === null) {
          onRun();
        }
      }}
    >
      <Stack gap="md">
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Kind of sound
          </Text>
          <SegmentedControl
            value={state.kind}
            onChange={chooseKind}
            data={catalog.kinds.map((entry) => ({ value: entry.id, label: entry.label }))}
          />
          <Text size="xs" c="dimmed">
            {KIND_HELP[state.kind]}
          </Text>
        </Stack>

        <Stack gap="xs">
          <Text size="sm" fw={600}>
            The brief
          </Text>
          <Text size="xs" c="dimmed">
            What the pipeline will know when it asks for this sound. The note under each box
            names the stage that will fill it. Only the description is needed.
          </Text>
          <Textarea
            label="Description"
            description="What you want, in your own words."
            placeholder="Quiet, sad piano under the scene where the old man reads the letter."
            value={state.brief.description}
            onChange={(event) => updateBrief({ description: event.currentTarget.value })}
            autosize
            minRows={2}
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            {boxesFor(state.kind).map((box) => {
              const common = {
                label: box.label,
                description: `Filled by the ${box.source}.`,
                value: state.brief[box.key] as string,
              };
              return box.multiline ? (
                <Textarea
                  key={box.key}
                  {...common}
                  onChange={(event) => updateBrief({ [box.key]: event.currentTarget.value })}
                  autosize
                  minRows={2}
                />
              ) : (
                <TextInput
                  key={box.key}
                  {...common}
                  onChange={(event) => updateBrief({ [box.key]: event.currentTarget.value })}
                />
              );
            })}
            <TextInput
              label="Length in seconds"
              description="Filled by the shot plan. Empty: the model's default."
              value={state.brief.durationS}
              onChange={(event) => updateBrief({ durationS: event.currentTarget.value })}
            />
          </SimpleGrid>
          {takesUnderNarration(state.kind) && (
            <Checkbox
              label="It plays under a narrator or dialogue"
              description="The writer then asks for a quiet, sparse sound that leaves room for the voice."
              checked={state.brief.underNarration}
              onChange={(event) => updateBrief({ underNarration: event.currentTarget.checked })}
            />
          )}
        </Stack>

        <Stack gap="xs">
          <Text size="sm" fw={600}>
            Models to compare
          </Text>
          {kindModels.map((info) => (
            <Group key={info.id} gap="xs" wrap="nowrap" align="flex-start">
              <Checkbox
                label={info.label}
                checked={chosen.some((entry) => entry.id === info.id)}
                onChange={(event) => toggleModel(info.id, event.currentTarget.checked)}
              />
              <LicenseBadge model={info} />
            </Group>
          ))}
          <Text size="xs" c="dimmed">
            Each model has its own fields and reads them differently, so each is written and
            edited on its own below. The first run on a model can take a few minutes: the
            GPU server stops idle workers after 10 minutes.
          </Text>
        </Stack>

        {chosen.length > 0 && (
          <Stack gap="sm">
            <Group justify="space-between">
              <Text size="sm" fw={600}>
                What each model is sent
              </Text>
              <Button
                size="compact-sm"
                variant="light"
                disabled={!briefReady || starting.length > 0}
                onClick={() => onWrite(chosen.map((info) => info.id))}
              >
                Write for all chosen models
              </Button>
            </Group>
            {chosen.map((info) => (
              <MusicModelFields
                key={info.id}
                info={info}
                values={valuesOf(state, info)}
                onChange={(values) => update({ values: { ...state.values, [info.id]: values } })}
                promptJobId={state.promptJobIds[info.id] ?? null}
                usedPromptJobId={state.usedPromptJobIds[info.id] ?? null}
                onWrite={() => onWrite([info.id])}
                canWrite={briefReady}
                starting={starting.includes(info.id)}
                onUse={(jobId, fields) =>
                  update({
                    values: { ...state.values, [info.id]: valuesFromFields(info, fields) },
                    usedPromptJobIds: { ...state.usedPromptJobIds, [info.id]: jobId },
                  })
                }
              />
            ))}
          </Stack>
        )}

        <Group align="flex-start" grow>
          <TextInput
            label="Variants"
            description={`How many seeds to try on each model, from 1 to ${MAX_VARIANTS}.`}
            value={state.variants}
            onChange={(event) => update({ variants: event.currentTarget.value })}
          />
          <TextInput
            label="Seed"
            description="Empty: random. Every model gets the same seeds."
            value={state.seed}
            onChange={(event) => update({ seed: event.currentTarget.value })}
          />
        </Group>

        <Stack gap={4} align="flex-start">
          <Button type="submit" loading={running} disabled={problem !== null}>
            Make the sound
          </Button>
          {problem !== null && (
            <Text size="xs" c="dimmed">
              {problem}
            </Text>
          )}
        </Stack>
      </Stack>
    </form>
  );
}
