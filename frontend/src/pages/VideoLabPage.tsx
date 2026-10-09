import { useState } from "react";
import { Alert, Paper, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../api/errors";
import { useCreateLabVideoRuns, type LabVideoRun } from "../api/videoLab";
import { VideoLabForm } from "../components/videoLab/VideoLabForm";
import { VideoLabRunList } from "../components/videoLab/VideoLabRunList";
import {
  DEFAULT_FORM,
  stateFromRuns,
  toRequest,
  type VideoLabFormState,
} from "../components/videoLab/videoLabView";

/**
 * A page for trying a prompt on LTX-2.3 and LTX-2.5 side by side, and for trying the multi-shot
 * prompts only LTX-2.5 can cut. Each run is a paid GPU job of 5 to 10 minutes that shares the
 * GPU slots of the scene clips. Every run is kept with its exact settings, so clips can be
 * compared later. It belongs to no project and changes none.
 */
export function VideoLabPage() {
  const [form, setForm] = useState<VideoLabFormState>(DEFAULT_FORM);
  const create = useCreateLabVideoRuns();

  function loadIntoForm(runs: LabVideoRun[]) {
    setForm(stateFromRuns(runs));
  }

  return (
    <Stack gap="lg" maw={1100}>
      <Stack gap={4}>
        <Title order={2}>Video lab</Title>
        <Text size="sm" c="dimmed">
          Try a prompt on LTX-2.3 and LTX-2.5 and compare the clips side by side. LTX-2.5 can cut
          between two to four shots inside one clip when the prompt names each cut in a sentence,
          and LTX-2.3 always makes one continuous shot. Each run is a paid GPU job of 5 to 10
          minutes, and it belongs to no project.
        </Text>
      </Stack>

      <Paper withBorder p="md" radius="md">
        <VideoLabForm
          state={form}
          onChange={setForm}
          onRun={() => create.mutate(toRequest(form))}
          running={create.isPending}
        />
      </Paper>

      {create.isError && (
        <Alert color="red" title="The runs were not started">
          {describeError(create.error)}
        </Alert>
      )}
      {create.isSuccess && (
        <Alert color="green" title="Started">
          {create.data.runs.length === 1 ? "The run is" : `${create.data.runs.length} runs are`}{" "}
          waiting for a free GPU slot and will appear below. You can leave this page: they keep
          going.
        </Alert>
      )}

      <Paper withBorder p="md" radius="md">
        <VideoLabRunList onLoad={loadIntoForm} />
      </Paper>
    </Stack>
  );
}
