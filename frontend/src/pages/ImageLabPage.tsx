import { useState } from "react";
import { Alert, Drawer, Loader, Paper, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../api/errors";
import { useLabRun, useRunLab, type LabImage, type LabRun } from "../api/imageLab";
import { LabForm } from "../components/imageLab/LabForm";
import { LabHistory } from "../components/imageLab/LabHistory";
import { LabRunView } from "../components/imageLab/LabRunView";
import {
  addReferences,
  DEFAULT_FORM,
  referenceFromImage,
  stateFromRun,
  toRequest,
  type LabFormState,
} from "../components/imageLab/labView";

/**
 * A page for testing Bitdeer's image API by hand: text to image, image to image and an edit,
 * with references from an upload, an earlier result or a project's frames. Every run is kept
 * with its exact request and answer, so results can be compared later. It belongs to no
 * project and changes none.
 */
export function ImageLabPage() {
  const [form, setForm] = useState<LabFormState>(DEFAULT_FORM);
  const [openRunId, setOpenRunId] = useState<number | null>(null);
  const run = useRunLab();
  const opened = useLabRun(openRunId);

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
        <Title order={2}>Image lab</Title>
        <Text size="sm" c="dimmed">
          Try Bitdeer's image API by hand and compare what comes back. Each setting is sent as you
          set it, and the answer is shown as it came, including a setting the API ignored or a call
          it refused. It is a paid call (about $0.035 per image), and it belongs to no project.
        </Text>
      </Stack>

      <Paper withBorder p="md" radius="md">
        <LabForm
          state={form}
          onChange={setForm}
          onRun={() => run.mutate(toRequest(form))}
          running={run.isPending}
        />
      </Paper>

      {run.isError && (
        <Alert color="red" title="The run was not made">
          {describeError(run.error)}
        </Alert>
      )}

      {run.data && (
        <Paper withBorder p="md" radius="md">
          <Stack gap="sm">
            <Title order={4}>Result</Title>
            <LabRunView run={run.data} onUseAsReference={addAsReference} onLoad={loadIntoForm} />
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
