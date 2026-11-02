import type { Dispatch, SetStateAction } from "react";
import { Alert, Paper, Stack, Text } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useCreateGraphicsRun } from "../../api/graphicsLab";
import { GraphicsLabForm } from "../graphicsLab/GraphicsLabForm";
import { GraphicsRunList } from "../graphicsLab/GraphicsRunList";
import { GraphicsRunPage } from "../graphicsLab/GraphicsRunPage";
import { toRequest, type GraphicsLabFormState } from "../graphicsLab/graphicsLabView";
import { useOpenGraphicsRun } from "../graphicsLab/useOpenGraphicsRun";

type GraphicsLabPanelProps = {
  /** The form lives in the Lab page, so changing tabs never loses what was typed. */
  form: GraphicsLabFormState;
  onFormChange: Dispatch<SetStateAction<GraphicsLabFormState>>;
};

/**
 * The Graphics tab: deterministic graphics (charts, diagrams and text cards drawn by code) made
 * from one line of an explainer script by four engines, to be compared side by side. This is the
 * foundation: a line becomes a run with four engine cards that are not built yet. The run is
 * the list, or one run's page when the address says which (`?run=`). It belongs to no project.
 */
export function GraphicsLabPanel({ form, onFormChange }: GraphicsLabPanelProps) {
  const [openId, openRun] = useOpenGraphicsRun();
  const create = useCreateGraphicsRun();

  if (openId !== null) {
    return (
      <Stack maw={1100}>
        <GraphicsRunPage runId={openId} onBack={() => openRun(null)} />
      </Stack>
    );
  }

  return (
    <Stack gap="lg" maw={1100}>
      <Text size="sm" c="dimmed">
        Type one line of an explainer script and make a run. A run is where the graphic for that line
        is made by four engines (Remotion templates, Python templates, Remotion building blocks and a
        generated component) and compared. The engines are built one by one: for now a run only shows
        its four empty cards. Making a run costs nothing, and it belongs to no project.
      </Text>

      <Paper withBorder p="md" radius="md">
        <GraphicsLabForm
          state={form}
          onChange={onFormChange}
          making={create.isPending}
          onMake={() =>
            create.mutate(toRequest(form), {
              onSuccess: (run) => openRun(run.id),
            })
          }
        />
      </Paper>

      {create.isError && (
        <Alert color="red" title="The run was not made">
          {describeError(create.error)}
        </Alert>
      )}

      <Paper withBorder p="md" radius="md">
        <GraphicsRunList onOpen={openRun} />
      </Paper>
    </Stack>
  );
}
