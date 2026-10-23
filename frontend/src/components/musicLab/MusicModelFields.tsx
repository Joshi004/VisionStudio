import { Alert, Button, Checkbox, Group, Paper, Select, Stack, Text, TextInput, Textarea } from "@mantine/core";

import { describeError } from "../../api/errors";
import { useJob } from "../../api/jobs";
import type { MusicFieldSpec, MusicModelInfo } from "../../api/musicLab";
import { isJobActive } from "../../api/polling";
import { useNow } from "../../hooks/useNow";
import { elapsedText } from "../jobs/jobFormat";
import { JobStatusBadge } from "../jobs/JobStatusBadge";
import { LicenseBadge, LicenseNotice } from "./MusicLicense";
import { hintFor, isShortText, rangeText, type FieldValue, type ModelValues } from "./musicLabView";

type MusicModelFieldsProps = {
  info: MusicModelInfo;
  values: ModelValues;
  onChange: (values: ModelValues) => void;
  /** The prompt-writing job started for this model, or null. */
  promptJobId: number | null;
  /** The prompt-writing job whose fields are in the boxes now, or null. */
  usedPromptJobId: number | null;
  /** Starts the job that writes this model's fields. */
  onWrite: () => void;
  /** Whether the brief is ready for the language model to write from. */
  canWrite: boolean;
  /** Whether the start of the job is being sent. */
  starting: boolean;
  /** Puts the written fields into the boxes. */
  onUse: (jobId: number, fields: Record<string, unknown>) => void;
};

/** What the finished job says (`job.output` is stored JSON, so it is read defensively). */
function readOutput(output: unknown): { fields: Record<string, unknown>; warnings: string[] } | null {
  if (typeof output !== "object" || output === null) {
    return null;
  }
  const record = output as Record<string, unknown>;
  if (typeof record.fields !== "object" || record.fields === null) {
    return null;
  }
  const warnings = Array.isArray(record.warnings)
    ? record.warnings.filter((item): item is string => typeof item === "string")
    : [];
  return { fields: record.fields as Record<string, unknown>, warnings };
}

function FieldInput({
  info,
  spec,
  value,
  onChange,
}: {
  info: MusicModelInfo;
  spec: MusicFieldSpec;
  value: FieldValue;
  onChange: (value: FieldValue) => void;
}) {
  if (spec.type === "flag") {
    return (
      <Checkbox
        label={spec.label}
        checked={value === true}
        onChange={(event) => onChange(event.currentTarget.checked)}
      />
    );
  }

  const text = typeof value === "string" ? value : "";
  const range = rangeText(spec);
  const hint = hintFor(info.id, spec);

  if (spec.choices !== null) {
    return (
      <Select
        label={spec.label}
        description={hint || undefined}
        data={spec.choices}
        value={text === "" ? null : text}
        onChange={(choice) => onChange(choice ?? "")}
        placeholder="The model chooses"
        clearable
      />
    );
  }

  if (spec.type === "int" || spec.type === "number") {
    return (
      <TextInput
        label={spec.label}
        description={[range, hint].filter((part) => part !== "").join(". ") || undefined}
        placeholder="Empty: the model or the lab chooses"
        value={text}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
    );
  }

  const counter = spec.max_chars === null ? "" : `${text.trim().length} of ${spec.max_chars} characters. `;
  if (isShortText(spec)) {
    return (
      <TextInput
        label={spec.label}
        description={`${counter}${hint}`.trim() || undefined}
        value={text}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
    );
  }
  return (
    <Textarea
      label={spec.required ? spec.label : `${spec.label} (optional)`}
      description={`${counter}${hint}`.trim()}
      value={text}
      onChange={(event) => onChange(event.currentTarget.value)}
      autosize
      minRows={2}
      maxRows={14}
    />
  );
}

/**
 * One chosen model: its licence warning, the button that has the language model write its
 * fields from the brief, and the fields themselves, which can always be edited by hand. A
 * written set is shown first and only goes into the boxes when you press "Use these fields",
 * so nothing you typed is overwritten.
 */
export function MusicModelFields({
  info,
  values,
  onChange,
  promptJobId,
  usedPromptJobId,
  onWrite,
  canWrite,
  starting,
  onUse,
}: MusicModelFieldsProps) {
  const job = useJob(promptJobId);
  const current = job.data;
  const active = isJobActive(current) || starting;
  const now = useNow(active, job.dataUpdatedAt);
  const result = current?.status === "succeeded" ? readOutput(current.output) : null;
  const alreadyUsed = current !== undefined && usedPromptJobId === current.id;

  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Group gap="xs">
            <Text size="sm" fw={600}>
              {info.label}
            </Text>
            <LicenseBadge model={info} />
          </Group>
          <Group gap="xs">
            {current && (
              <Group gap="xs">
                <JobStatusBadge job={current} />
                <Text size="xs" c="dimmed">
                  {elapsedText(current, now)}
                </Text>
              </Group>
            )}
            <Button size="compact-sm" variant="light" onClick={onWrite} disabled={!canWrite || active} loading={starting}>
              Write with the language model
            </Button>
          </Group>
        </Group>

        <LicenseNotice model={info} />

        {current?.status === "failed" && current.error && (
          <Alert color="red" title="The fields could not be written">
            <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {current.error}
            </Text>
          </Alert>
        )}

        {result && (
          <Paper withBorder p="xs" radius="sm" bg="var(--mantine-color-gray-0)">
            <Stack gap="xs">
              <Text size="xs" fw={600}>
                Written by the language model
              </Text>
              {Object.entries(result.fields)
                .filter(([, value]) => value !== null && value !== "" && value !== false)
                .map(([name, value]) => (
                  <Text key={name} size="xs" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                    <b>{info.fields.find((spec) => spec.name === name)?.label ?? name}:</b>{" "}
                    {typeof value === "string" ? value : JSON.stringify(value)}
                  </Text>
                ))}
              {result.warnings.length > 0 && (
                <Alert color="yellow" title="Check before you use it" p="xs">
                  <Stack gap={2}>
                    {result.warnings.map((warning) => (
                      <Text key={warning} size="xs">
                        {warning}
                      </Text>
                    ))}
                  </Stack>
                </Alert>
              )}
              <Group>
                <Button
                  size="compact-sm"
                  variant={alreadyUsed ? "default" : "filled"}
                  disabled={alreadyUsed}
                  onClick={() => current && onUse(current.id, result.fields)}
                >
                  {alreadyUsed ? "In the boxes below" : "Use these fields"}
                </Button>
              </Group>
            </Stack>
          </Paper>
        )}

        {job.isError && (
          <Alert color="red" title="Could not load the written fields">
            {describeError(job.error)}
          </Alert>
        )}

        {info.fields.map((spec) => (
          <FieldInput
            key={spec.name}
            info={info}
            spec={spec}
            value={values[spec.name] ?? (spec.type === "flag" ? false : "")}
            onChange={(value) => onChange({ ...values, [spec.name]: value })}
          />
        ))}
      </Stack>
    </Paper>
  );
}
