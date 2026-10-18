import type { Dispatch, SetStateAction } from "react";
import { Alert, Paper, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useCreateH3ReferenceRun,
  useCreateLabVideoRuns,
  type LabVideoRun,
} from "../../api/videoLab";
import { VideoLabForm } from "../videoLab/VideoLabForm";
import { VideoLabRunList } from "../videoLab/VideoLabRunList";
import {
  stateFromRuns,
  toReferenceRequest,
  toRequest,
  type VideoLabFormState,
} from "../videoLab/videoLabView";

type VideoLabPanelProps = {
  /** The form lives in the Lab page, so the library drawer can fill it from any tab. */
  form: VideoLabFormState;
  onFormChange: Dispatch<SetStateAction<VideoLabFormState>>;
};

/**
 * The Video lab tab: trying a prompt on LTX-2.3, LTX-2.5 and MiniMax H3 side by side, trying the
 * multi-shot prompts only LTX-2.5 can cut, and making a MiniMax H3 clip from reference pictures
 * (one or two characters, a scene) and optional voices. Each run is a paid GPU job of 5 to 10
 * minutes or more (MiniMax H3 holds the 4 or 8 GPUs the server reports, and shows its estimate)
 * that shares the GPU slots of the scene clips. Every run is kept with its exact settings, so
 * clips can be compared later. It belongs to no project and changes none.
 */
export function VideoLabPanel({ form, onFormChange }: VideoLabPanelProps) {
  const create = useCreateLabVideoRuns();
  const createReference = useCreateH3ReferenceRun();
  // The two modes start runs differently; the page shows what the mode in the form did last.
  const started = form.kind === "h3_reference" ? createReference : create;

  function loadIntoForm(runs: LabVideoRun[]) {
    onFormChange(stateFromRuns(runs));
  }

  function run() {
    if (form.kind === "h3_reference") {
      createReference.mutate(toReferenceRequest(form));
    } else {
      create.mutate(toRequest(form));
    }
  }

  return (
    <Stack gap="lg" maw={1100}>
      <Text size="sm" c="dimmed">
        Try a prompt on LTX-2.3, LTX-2.5 and MiniMax H3 and compare the clips side by side. LTX-2.5
        can cut between two to four shots inside one clip when the prompt names each cut in a
        sentence, LTX-2.3 always makes one continuous shot, and MiniMax H3 makes its own sound with
        the picture and reads a structured prompt. Each run is a paid GPU job of 5 to 10 minutes
        (MiniMax H3: more, on the GPUs the server chooses), and it belongs to no project. To make a character speak a
        line in its own voice, use the Characters tab.
      </Text>

      <Paper withBorder p="md" radius="md">
        <VideoLabForm
          state={form}
          onChange={onFormChange}
          onRun={run}
          running={started.isPending}
        />
      </Paper>

      {started.isError && (
        <Alert color="red" title="The runs were not started">
          {describeError(started.error)}
        </Alert>
      )}
      {started.isSuccess && (
        <Alert color="green" title="Started">
          {started.data.runs.length === 1 ? "The run is" : `${started.data.runs.length} runs are`}{" "}
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
