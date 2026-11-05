import type { Dispatch, SetStateAction } from "react";
import { Alert, Paper, Stack, Text, Title } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useCreateGraphicsRun } from "../../api/graphicsLab";
import { GraphicsLabForm } from "../graphicsLab/GraphicsLabForm";
import { GraphicsRunList } from "../graphicsLab/GraphicsRunList";
import { GraphicsRunPage } from "../graphicsLab/GraphicsRunPage";
import { GraphicsTestCardPanel } from "../graphicsLab/GraphicsTestCardPanel";
import { GraphicsTrialPanel } from "../graphicsLab/GraphicsTrialPanel";
import { GraphicsTrialSummary } from "../graphicsLab/GraphicsTrialSummary";
import { toRequest, type GraphicsLabFormState } from "../graphicsLab/graphicsLabView";
import { useOpenGraphicsRun } from "../graphicsLab/useOpenGraphicsRun";
import { useOpenGraphicsTrial } from "../graphicsLab/useOpenGraphicsTrial";

type GraphicsLabPanelProps = {
  /** The form lives in the Lab page, so changing tabs never loses what was typed. */
  form: GraphicsLabFormState;
  onFormChange: Dispatch<SetStateAction<GraphicsLabFormState>>;
};

/**
 * The Graphics tab: deterministic graphics (charts, diagrams and text cards drawn by code) made
 * from one line of an explainer script by four engines, to be compared side by side. A line becomes
 * a run, whose page holds the director's brief (a paid call, from a click) and four engine cards.
 * The panel is the list, or one run's page when the address says which (`?run=`), or a trial
 * set's summary (`?trial=`, GFX-012; a run opened from it goes over it and closing the run returns
 * to it). It belongs to no project.
 */
export function GraphicsLabPanel({ form, onFormChange }: GraphicsLabPanelProps) {
  const [openId, openRun] = useOpenGraphicsRun();
  const [openSet, openTrial] = useOpenGraphicsTrial();
  const create = useCreateGraphicsRun();

  if (openId !== null) {
    return (
      <Stack maw={1100}>
        <GraphicsRunPage runId={openId} onBack={() => openRun(null)} onOpenRun={openRun} />
      </Stack>
    );
  }

  if (openSet !== null) {
    return (
      <Stack maw={1100}>
        <GraphicsTrialSummary
          setNo={openSet}
          onBack={() => openTrial(null)}
          onOpenTrial={openTrial}
          onOpenRun={openRun}
        />
      </Stack>
    );
  }

  return (
    <Stack gap="lg" maw={1100}>
      <Text size="sm" c="dimmed">
        Type one line of an explainer script and make a run. A run is where the graphic for that line
        is made by four engines (Remotion templates, Python templates, Remotion building blocks and a
        generated component) and compared. The engines are built one by one. Making a run with no
        voice costs nothing; with a saved voice it starts a speech job on the remote server. Writing
        the brief is a paid model call that starts only when you press the button. A run belongs to
        no project.
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

      <Paper withBorder p="md" radius="md">
        <Stack gap="xs">
          <Title order={4}>Trial batch</Title>
          <GraphicsTrialPanel onOpenTrial={openTrial} />
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Stack gap="xs">
          <Title order={4}>Motion service test card</Title>
          <GraphicsTestCardPanel />
        </Stack>
      </Paper>
    </Stack>
  );
}
