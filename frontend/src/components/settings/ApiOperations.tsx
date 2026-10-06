import { Accordion, Badge, Code, Group, Stack, Text } from "@mantine/core";

import type { components } from "../../api/schema";

type TagGroup = components["schemas"]["TagGroupOut"];

const METHOD_COLORS: Record<string, string> = {
  GET: "green",
  POST: "blue",
  PUT: "orange",
  PATCH: "orange",
  DELETE: "red",
};

/** The operations of the approved OpenAPI document, one section per tag. */
export function ApiOperations({ tags }: { tags: TagGroup[] }) {
  return (
    <Accordion multiple variant="contained" radius="md">
      {tags.map((group) => (
        <Accordion.Item key={group.tag} value={group.tag}>
          <Accordion.Control>
            {group.tag} ({group.operations.length})
          </Accordion.Control>
          <Accordion.Panel>
            <Stack gap={6}>
              {group.operations.map((operation) => (
                <Group key={`${operation.method} ${operation.path}`} gap="xs" wrap="nowrap">
                  <Badge
                    color={METHOD_COLORS[operation.method] ?? "gray"}
                    variant="light"
                    w={72}
                    style={{ flexShrink: 0 }}
                  >
                    {operation.method}
                  </Badge>
                  <Code>{operation.path}</Code>
                  {operation.summary && (
                    <Text size="xs" c="dimmed">
                      {operation.summary}
                    </Text>
                  )}
                </Group>
              ))}
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion>
  );
}
