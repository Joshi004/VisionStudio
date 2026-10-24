import { useState, type Dispatch, type SetStateAction } from "react";
import { Alert, Loader, Paper, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useCreateMusicLabRuns,
  useCreateMusicPromptDraft,
  useMusicCatalog,
  type LabMusicRun,
  type MusicModel,
} from "../../api/musicLab";
import { MusicEditPanel } from "../musicLab/MusicEditPanel";
import { MusicLabForm } from "../musicLab/MusicLabForm";
import { MusicLabRunList } from "../musicLab/MusicLabRunList";
import type { MusicEditFormState } from "../musicLab/musicEditView";
import { briefRequest, selectedModels, toRequest, type MusicLabFormState } from "../musicLab/musicLabView";

type MusicLabPanelProps = {
  /** The form lives in the Lab page, so changing tabs never loses what was typed. */
  form: MusicLabFormState;
  onFormChange: Dispatch<SetStateAction<MusicLabFormState>>;
  /** The edit form lives in the Lab page for the same reason. */
  editForm: MusicEditFormState;
  onEditFormChange: Dispatch<SetStateAction<MusicEditFormState>>;
};

/**
 * The Music lab tab: trying the music and sound models of the GPU server (ACE-Step 1.5, YuE 2,
 * Stable Audio 3, Stable Audio Open and LTX audio) on the same brief, to hear which kind of
 * sound each does best. A language model can write each model's fields from the brief. Each run
 * is a paid GPU job. It belongs to no project and changes none.
 */
export function MusicLabPanel({ form, onFormChange, editForm, onEditFormChange }: MusicLabPanelProps) {
  const catalog = useMusicCatalog();
  const create = useCreateMusicLabRuns();
  const draft = useCreateMusicPromptDraft();
  const [starting, setStarting] = useState<MusicModel[]>([]);
  const [draftError, setDraftError] = useState<string | null>(null);

  /** Has the language model write the fields of each of these models from the brief. */
  async function writeFields(models: MusicModel[]) {
    if (catalog.data === undefined) {
      return;
    }
    const brief = briefRequest(form.kind, form.brief);
    setDraftError(null);
    setStarting((current) => [...current, ...models]);
    // One job a model, started one after the other so each shows as soon as it exists.
    for (const model of models) {
      try {
        const job = await draft.mutateAsync({ model, kind: form.kind, brief });
        onFormChange((current) => ({
          ...current,
          promptJobIds: { ...current.promptJobIds, [model]: job.id },
        }));
      } catch (error) {
        setDraftError(describeError(error));
      } finally {
        setStarting((current) => current.filter((entry) => entry !== model));
      }
    }
  }

  /** Fills the edit form with this run as the source, and brings the form into view. */
  function editRun(run: LabMusicRun) {
    const description = typeof run.brief.description === "string" ? run.brief.description : "";
    onEditFormChange((current) => ({
      ...current,
      sourceMode: "run",
      runNumber: String(run.id),
      kind: run.kind,
      description: current.description.trim() === "" ? description : current.description,
    }));
    document.getElementById("music-edit")?.scrollIntoView({ behavior: "smooth" });
  }

  if (catalog.isLoading) {
    return <Loader size="sm" />;
  }
  if (catalog.data === undefined) {
    return (
      <Alert color="red" title="Could not load the music models">
        {catalog.error ? describeError(catalog.error) : "The server did not answer."}
      </Alert>
    );
  }

  const count = selectedModels(form, catalog.data).length * (Number(form.variants) || 1);

  return (
    <Stack gap="lg" maw={1100}>
      <Text size="sm" c="dimmed">
        Try the music and sound models of the GPU server on one brief and listen to them side by
        side. Choose the kind of sound, describe it, and the models that make it. The language
        model can write each model's fields in the way that model reads them, and you can edit
        them before you run. Each run is a paid GPU job, and it belongs to no project.
      </Text>

      <Paper withBorder p="md" radius="md">
        <MusicLabForm
          state={form}
          onChange={onFormChange}
          catalog={catalog.data}
          onRun={() => create.mutate(toRequest(form, catalog.data))}
          running={create.isPending}
          onWrite={(models) => void writeFields(models)}
          starting={starting}
        />
      </Paper>

      {draftError !== null && (
        <Alert color="red" title="The prompt was not started">
          {draftError}
        </Alert>
      )}
      {create.isError && (
        <Alert color="red" title="The runs were not started">
          {describeError(create.error)}
        </Alert>
      )}
      {create.isSuccess && (
        <Alert color="green" title="Started">
          {count === 1 ? "The run is" : `${count} runs are`} waiting for a free GPU slot and will
          appear below. You can leave this page: it keeps going.
        </Alert>
      )}

      <Paper withBorder p="md" radius="md" id="music-edit">
        <MusicEditPanel state={editForm} onChange={onEditFormChange} catalog={catalog.data} />
      </Paper>

      <Paper withBorder p="md" radius="md">
        <MusicLabRunList onLoad={onFormChange} onEdit={editRun} />
      </Paper>
    </Stack>
  );
}
