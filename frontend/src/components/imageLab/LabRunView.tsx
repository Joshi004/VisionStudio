import { useState } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Code,
  Collapse,
  Group,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";

import type { LabImage, LabRun } from "../../api/imageLab";
import { formatBytes, formatDateTime } from "../../format";
import { costLine, MODE_LABELS, paramsLine } from "./labView";

type LabRunViewProps = {
  run: LabRun;
  /** Offered for each result image. */
  onUseAsReference?: (image: LabImage) => void;
  /** Fills the form with this run's settings. */
  onLoad?: (run: LabRun) => void;
};

function Json({ label, value }: { label: string; value: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <Stack gap={4}>
      <Button
        size="compact-xs"
        variant="subtle"
        onClick={() => setOpen(!open)}
        style={{ alignSelf: "flex-start" }}
      >
        {open ? `Hide ${label}` : `Show ${label}`}
      </Button>
      <Collapse expanded={open}>
        <Code block style={{ maxHeight: 380, overflow: "auto", fontSize: 12 }}>
          {JSON.stringify(value, null, 2)}
        </Code>
      </Collapse>
    </Stack>
  );
}

/** One run: what was asked, what came back, and the exact request and answer. */
export function LabRunView({ run, onUseAsReference, onLoad }: LabRunViewProps) {
  const [added, setAdded] = useState<number | null>(null);
  const cost = costLine(run);

  return (
    <Stack gap="sm">
      <Group gap="sm" align="center">
        <Badge color={run.status === "succeeded" ? "green" : "red"} variant="light">
          {run.status}
        </Badge>
        <Text size="sm" fw={600}>
          Run {run.id} · {MODE_LABELS[run.mode]}
        </Text>
        <Text size="sm" c="dimmed">
          {formatDateTime(run.created_at)}
        </Text>
        {onLoad && (
          <Button size="compact-sm" variant="default" onClick={() => onLoad(run)}>
            Load into form
          </Button>
        )}
      </Group>

      <Text size="sm" c="dimmed">
        {[
          run.seconds !== null ? `${run.seconds.toFixed(1)} s` : null,
          run.http_status !== null ? `HTTP ${run.http_status}` : "no answer",
          run.endpoint,
          run.model,
          run.request_bytes !== null ? `${formatBytes(run.request_bytes)} sent` : null,
          cost,
        ]
          .filter((part) => part !== null)
          .join(" · ")}
      </Text>
      <Text size="xs" c="dimmed">
        {paramsLine(run)}
      </Text>

      {run.error && (
        <Alert color="red" title="The call did not give an image">
          <Text size="sm" style={{ wordBreak: "break-word" }}>
            {run.error}
          </Text>
        </Alert>
      )}
      {run.status === "succeeded" && run.references.length > 0 && run.images.length > 0 && (
        <Text size="xs" c="dimmed">
          Compare the result with the {run.references.length}{" "}
          {run.references.length === 1 ? "reference" : "references"} below: an API that ignores them
          still answers 200.
        </Text>
      )}

      {run.images.length > 0 && (
        <SimpleGrid cols={{ base: 1, sm: Math.min(run.images.length, 2) }} spacing="md">
          {run.images.map((image) => (
            <Stack key={image.id} gap={4}>
              <a href={image.url} target="_blank" rel="noreferrer">
                <img
                  src={image.url}
                  alt={`Result ${image.output_index !== null ? image.output_index + 1 : ""} of run ${run.id}`}
                  style={{ width: "100%", borderRadius: 6, display: "block" }}
                />
              </a>
              <Text size="xs" c="dimmed">
                {image.width} x {image.height} · {formatBytes(image.size_bytes)} · {image.mime}
              </Text>
              <Group gap="xs">
                <Button
                  size="compact-xs"
                  variant="default"
                  component="a"
                  href={image.url}
                  download={`image-lab-run-${run.id}-${(image.output_index ?? 0) + 1}.${image.mime === "image/png" ? "png" : image.mime === "image/webp" ? "webp" : "jpg"}`}
                >
                  Download
                </Button>
                {onUseAsReference && (
                  <Button
                    size="compact-xs"
                    variant="light"
                    onClick={() => {
                      onUseAsReference(image);
                      setAdded(image.id);
                    }}
                  >
                    Use as reference
                  </Button>
                )}
                {added === image.id && (
                  <Text size="xs" c="green">
                    Added to the form
                  </Text>
                )}
              </Group>
            </Stack>
          ))}
        </SimpleGrid>
      )}

      <Stack gap={2}>
        <Text size="sm" fw={600}>
          Prompt
        </Text>
        <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {run.prompt}
        </Text>
      </Stack>

      {run.references.length > 0 && (
        <Stack gap={4}>
          <Text size="sm" fw={600}>
            References sent ({run.references.length})
          </Text>
          <SimpleGrid cols={{ base: 3, sm: 5 }} spacing="xs">
            {run.references.map((reference, index) => (
              <Stack key={`${reference.source}-${reference.id}-${index}`} gap={2}>
                {reference.url ? (
                  <a href={reference.url} target="_blank" rel="noreferrer">
                    <img
                      src={reference.url}
                      alt={`Reference ${index + 1}`}
                      style={{ width: "100%", borderRadius: 4, display: "block" }}
                    />
                  </a>
                ) : (
                  <Text size="xs" c="red">
                    gone
                  </Text>
                )}
                <Text size="xs" c="dimmed">
                  image {index + 1} ·{" "}
                  {reference.source === "lab" ? `lab ${reference.id}` : `frame ${reference.id}`}
                </Text>
              </Stack>
            ))}
          </SimpleGrid>
        </Stack>
      )}

      {run.usage && <Json label="usage" value={run.usage} />}
      {run.request !== null && run.request !== undefined && (
        <Json label="the request (images replaced by their sizes)" value={run.request} />
      )}
      {run.response !== null && run.response !== undefined && (
        <Json label="the answer (images replaced by their sizes)" value={run.response} />
      )}
      {run.status === "succeeded" && (
        <Text size="xs" c="dimmed">
          Images are stored exactly as returned.{" "}
          <Anchor href={run.images[0]?.url} target="_blank" rel="noreferrer" size="xs">
            Open the first one at full size
          </Anchor>
          .
        </Text>
      )}
    </Stack>
  );
}
