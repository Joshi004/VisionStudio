import { useState } from "react";
import { Badge, Button, Code, Group, Paper, Stack, Table, Text, Title } from "@mantine/core";

import { formatDateTime } from "../../format";
import { JobDetailDrawer } from "../jobs/JobDetailDrawer";

type Primitive = string | number | boolean | null;

type ArtifactViewerProps = {
  title: string;
  /** The artifact's version number. */
  version: number;
  /** Who made it: the model, or a person's edit (the provenance convention in DATABASE_STRUCTURE.md). */
  source: "ai" | "manual";
  /** The job that produced it, or null for a manual edit. */
  jobId: number | null;
  createdAt?: string;
  /** The artifact itself, as the API returned it. */
  data: unknown;
};

function isPrimitive(value: unknown): value is Primitive {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

/** A plain object whose values are all single values, which a two-column table can show. */
function isFlat(value: unknown): value is Record<string, Primitive> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.values(value).every(isPrimitive)
  );
}

function showValue(value: Primitive): string {
  return value === null ? "—" : String(value);
}

function ArtifactData({ data }: { data: unknown }) {
  if (isFlat(data)) {
    return (
      <Table verticalSpacing="xs">
        <Table.Tbody>
          {Object.entries(data).map(([key, value]) => (
            <Table.Tr key={key}>
              <Table.Td w={180}>
                <Text size="sm" c="dimmed">
                  {key}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm" style={{ wordBreak: "break-word", whiteSpace: "pre-wrap" }}>
                  {showValue(value)}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    );
  }
  return (
    <Code block style={{ maxHeight: 420, overflow: "auto" }}>
      {JSON.stringify(data, null, 2)}
    </Code>
  );
}

/**
 * Shows one stage artifact, read only: its version, who made it, the job behind it and its
 * content. Every later stage shows its result with this component.
 */
export function ArtifactViewer({
  title,
  version,
  source,
  jobId,
  createdAt,
  data,
}: ArtifactViewerProps) {
  const [openJobId, setOpenJobId] = useState<number | null>(null);

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>{title}</Title>
            {createdAt && (
              <Text size="xs" c="dimmed">
                {formatDateTime(createdAt)}
              </Text>
            )}
          </Stack>
          <Group gap="xs">
            <Badge variant="light">Version {version}</Badge>
            <Badge variant="light" color={source === "ai" ? "violet" : "teal"}>
              {source === "ai" ? "AI" : "Manual"}
            </Badge>
            {jobId !== null && (
              <Button size="compact-xs" variant="default" onClick={() => setOpenJobId(jobId)}>
                Job {jobId}
              </Button>
            )}
          </Group>
        </Group>
        <ArtifactData data={data} />
      </Stack>
      <JobDetailDrawer jobId={openJobId} onClose={() => setOpenJobId(null)} />
    </Paper>
  );
}
