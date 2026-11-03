import { Alert, Anchor, Code, Collapse, Group, Loader, Stack, Text } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";

import type { GraphicRender } from "../../api/graphicsLab";
import { isJobActive } from "../../api/polling";
import { readComponentInput } from "./graphicsLabView";

type GraphicsComponentCodeProps = {
  /** The newest render of the generated-component engine. */
  render: GraphicRender;
};

/**
 * What the generated-component engine draws from: the code the model wrote (folded), what the
 * browser check found, and the warnings about numbers that are not traced to a fact. While the
 * component is being written it says so.
 */
export function GraphicsComponentCode({ render }: GraphicsComponentCodeProps) {
  const component = readComponentInput(render.input);
  const [showCode, { toggle }] = useDisclosure(false);

  if (isJobActive(render.input_job)) {
    return (
      <Group gap="xs">
        <Loader size="xs" />
        <Text size="xs" c="dimmed">
          Writing the component{render.input_job?.phase ? `: ${render.input_job.phase}` : ""}
        </Text>
      </Group>
    );
  }
  if (component === null) {
    return null;
  }

  return (
    <Stack gap={6}>
      {!component.checked ? (
        <Text size="xs" c="dimmed" style={{ wordBreak: "break-word" }}>
          The component was not checked{component.reason ? `: ${component.reason}` : "."}
        </Text>
      ) : component.passed === false ? (
        <Alert color="red" p="xs" title="The component does not work">
          <Stack gap={2}>
            {component.errors.map((error) => (
              <Text key={error} size="xs" style={{ wordBreak: "break-word" }}>
                {error}
              </Text>
            ))}
          </Stack>
        </Alert>
      ) : (
        <Text size="xs" c="dimmed">
          Compiled and drawn without errors
          {component.askedAgain ? " (after asking the model again)" : ""}.
        </Text>
      )}
      {component.warnings.length > 0 && (
        <Alert color="yellow" p="xs" title="Numbers not traced to the line">
          <Stack gap={2}>
            {component.warnings.map((warning) => (
              <Text key={warning} size="xs" style={{ wordBreak: "break-word" }}>
                {warning}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}
      <Anchor component="button" type="button" size="xs" onClick={toggle} ta="left">
        {showCode ? "Hide the code" : "Show the code"}
      </Anchor>
      <Collapse expanded={showCode}>
        <Code block style={{ maxHeight: 280, overflow: "auto" }}>
          {component.code}
        </Code>
      </Collapse>
    </Stack>
  );
}
