import { Badge, Code, Group, Stack, Text } from "@mantine/core";

import type { ContractDiff as ContractDiffData } from "../../api/gpu";

const KIND_COLORS = { added: "green", removed: "red", changed: "yellow" } as const;

function NameList({ label, names }: { label: string; names: string[] }) {
  if (names.length === 0) {
    return null;
  }
  return (
    <Stack gap={2}>
      <Text size="sm" fw={500}>
        {label} ({names.length})
      </Text>
      <Group gap={6}>
        {names.map((name) => (
          <Code key={name}>{name}</Code>
        ))}
      </Group>
    </Stack>
  );
}

/** What differs between the approved version of a source and another version of it. */
export function ContractDiff({ diff }: { diff: ContractDiffData }) {
  const openapi = diff.openapi;
  const hasDetails = diff.entries.length > 0 || (openapi !== null && hasOpenApiChanges(openapi));

  return (
    <Stack gap="sm">
      {openapi && (
        <>
          <NameList label="Operations added" names={openapi.operations_added} />
          <NameList label="Operations removed" names={openapi.operations_removed} />
          <NameList label="Operations changed" names={openapi.operations_changed} />
          <NameList label="Schemas added" names={openapi.schemas_added} />
          <NameList label="Schemas removed" names={openapi.schemas_removed} />
          <NameList label="Schemas changed" names={openapi.schemas_changed} />
        </>
      )}

      {!hasDetails && (
        <Text size="sm" c="dimmed">
          The fingerprint changed, but no field in the document differs.
        </Text>
      )}

      {diff.entries.map((entry) => (
        <Stack key={`${entry.kind}|${entry.path}`} gap={2}>
          <Group gap="xs">
            <Badge color={KIND_COLORS[entry.kind]} variant="light">
              {entry.kind}
            </Badge>
            <Code>{entry.path}</Code>
          </Group>
          {entry.before !== null && (
            <Text size="xs" c="red" ff="monospace" style={{ wordBreak: "break-all" }}>
              - {entry.before}
            </Text>
          )}
          {entry.after !== null && (
            <Text size="xs" c="green" ff="monospace" style={{ wordBreak: "break-all" }}>
              + {entry.after}
            </Text>
          )}
          {entry.text_diff && entry.text_diff.length > 0 && (
            <Code block>{entry.text_diff.join("\n")}</Code>
          )}
        </Stack>
      ))}

      {diff.truncated && (
        <Text size="xs" c="dimmed">
          More changes exist than are shown here.
        </Text>
      )}
    </Stack>
  );
}

function hasOpenApiChanges(openapi: NonNullable<ContractDiffData["openapi"]>): boolean {
  return (
    openapi.operations_added.length > 0 ||
    openapi.operations_removed.length > 0 ||
    openapi.operations_changed.length > 0 ||
    openapi.schemas_added.length > 0 ||
    openapi.schemas_removed.length > 0 ||
    openapi.schemas_changed.length > 0
  );
}
