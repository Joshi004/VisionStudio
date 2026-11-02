import { Alert, Anchor, Badge, Code, Collapse, Group, Loader, Stack, Text } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";

import type { GraphicRender } from "../../api/graphicsLab";
import { isJobActive } from "../../api/polling";
import { readTemplateInput, TEMPLATE_LABELS } from "./graphicsLabView";

type GraphicsTemplateSpecProps = {
  /** The newest render of a template engine. */
  render: GraphicRender;
};

/**
 * What a template engine draws from: the template spec the model wrote (both template engines
 * share one), or the reason that no template fits. While the spec is being written it says so.
 */
export function GraphicsTemplateSpec({ render }: GraphicsTemplateSpecProps) {
  const spec = readTemplateInput(render.input);
  const [showSpec, { toggle }] = useDisclosure(false);

  if (isJobActive(render.input_job)) {
    return (
      <Group gap="xs">
        <Loader size="xs" />
        <Text size="xs" c="dimmed">
          Writing the template spec{render.input_job?.phase ? `: ${render.input_job.phase}` : ""}
        </Text>
      </Group>
    );
  }
  if (spec === null) {
    return null;
  }

  return (
    <Stack gap={6}>
      {spec.kind === "no_fit" ? (
        <Alert color="yellow" p="xs" title="No template fits">
          <Text size="xs" style={{ wordBreak: "break-word" }}>
            {spec.reason}
          </Text>
        </Alert>
      ) : (
        <>
          <Group gap="xs">
            <Badge variant="light">{TEMPLATE_LABELS[spec.template] ?? spec.template}</Badge>
            {spec.variant !== null && (
              <Text size="xs" c="dimmed">
                {spec.variant}
              </Text>
            )}
          </Group>
          <Anchor component="button" type="button" size="xs" onClick={toggle} ta="left">
            {showSpec ? "Hide the spec" : "Show the spec"}
          </Anchor>
          <Collapse expanded={showSpec}>
            <Code block style={{ maxHeight: 280, overflow: "auto" }}>
              {JSON.stringify(render.input, null, 2)}
            </Code>
          </Collapse>
        </>
      )}
    </Stack>
  );
}
