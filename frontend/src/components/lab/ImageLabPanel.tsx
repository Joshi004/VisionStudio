import { useState, type Dispatch, type SetStateAction } from "react";
import { Alert, Drawer, Loader, Paper, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useLabRun,
  useRunLab,
  useRunQwenLab,
  type LabEngine,
  type LabImage,
  type LabRun,
} from "../../api/imageLab";
import { LabForm } from "../imageLab/LabForm";
import { LabHistory } from "../imageLab/LabHistory";
import { LabRunView } from "../imageLab/LabRunView";
import {
  addReferences,
  referenceFromImage,
  stateFromRun,
  toQwenRequest,
  toRequest,
  type LabFormState,
} from "../imageLab/labView";

type ImageLabPanelProps = {
  /** The form lives in the Lab page, so the library drawer can fill it from any tab. */
  form: LabFormState;
  onFormChange: Dispatch<SetStateAction<LabFormState>>;
};

/**
 * The Image lab tab: testing two image models by hand and comparing what they make.
 * Qwen-Image-2.1 runs on your GPU server (text to image, a few minutes, no price). Seedream is
 * Bitdeer's paid API (text to image, image to image and an edit, with references from an upload,
 * an earlier result or a project's frames). Every run is kept with its exact request and answer,
 * so results can be compared later. It belongs to no project and changes none.
 */
export function ImageLabPanel({ form, onFormChange: setForm }: ImageLabPanelProps) {
  const [openRunId, setOpenRunId] = useState<number | null>(null);
  // The model of the run the Result panel shows, and the Qwen run it follows.
  const [shown, setShown] = useState<LabEngine | null>(null);
  const [qwenRunId, setQwenRunId] = useState<number | null>(null);
  const run = useRunLab();
  const qwen = useRunQwenLab();
  const qwenRun = useLabRun(qwenRunId);
  const opened = useLabRun(openRunId);

  function start() {
    if (form.engine === "qwen") {
      setShown("qwen");
      qwen.mutate(toQwenRequest(form), { onSuccess: (started) => setQwenRunId(started.id) });
    } else {
      setShown("seedream");
      run.mutate(toRequest(form));
    }
  }

  // The Qwen run is polled by id; until the first answer, the run the start returned stands in.
  const result = shown === "qwen" ? (qwenRun.data ?? qwen.data) : run.data;
  const startError = shown === "qwen" ? qwen.error : run.error;

  function addAsReference(image: LabImage) {
    setForm((current) => ({
      ...current,
      references: addReferences(current.references, [referenceFromImage(image)]).items,
    }));
  }

  function loadIntoForm(source: LabRun) {
    setForm(stateFromRun(source));
    setOpenRunId(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <Stack gap="lg" maw={1100}>
      <Stack gap={4}>
        <Text size="sm" c="dimmed">
          Try an image model by hand and compare what comes back: Qwen-Image-2.1 on your GPU server
          (the model that makes the first frames) or Seedream on Bitdeer. Each setting is sent as
          you set it, and the answer is shown as it came, including a setting the model ignored or a
          call it refused. Seedream is a paid call (about $0.035 per image). Nothing here belongs
          to a project.
        </Text>
      </Stack>

      <Paper withBorder p="md" radius="md">
        <LabForm
          state={form}
          onChange={setForm}
          onRun={start}
          running={run.isPending}
          starting={qwen.isPending}
        />
      </Paper>

      {startError !== null && (
        <Alert color="red" title="The run was not started">
          {describeError(startError)}
        </Alert>
      )}

      {result && (
        <Paper withBorder p="md" radius="md">
          <Stack gap="sm">
            <Title order={4}>Result</Title>
            <LabRunView run={result} onUseAsReference={addAsReference} onLoad={loadIntoForm} />
          </Stack>
        </Paper>
      )}

      <Paper withBorder p="md" radius="md">
        <LabHistory onOpen={setOpenRunId} />
      </Paper>

      <Drawer
        opened={openRunId !== null}
        onClose={() => setOpenRunId(null)}
        position="right"
        size="xl"
        title={
          <Title order={4} component="span">
            Run {openRunId}
          </Title>
        }
      >
        {opened.isLoading && <Loader size="sm" />}
        {opened.isError && (
          <Alert color="red" title="Could not load the run">
            {describeError(opened.error)} Press Refresh to try again.
          </Alert>
        )}
        {opened.data && (
          <LabRunView run={opened.data} onUseAsReference={addAsReference} onLoad={loadIntoForm} />
        )}
      </Drawer>
    </Stack>
  );
}
