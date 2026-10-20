import { useState } from "react";
import { Alert, Button, Group, SegmentedControl, Stack, Text, TextInput, Textarea } from "@mantine/core";

import {
  useCreateEnvironment,
  useEditEnvironment,
  type LibraryEnvironment,
} from "../../api/environmentLab";
import { describeError } from "../../api/errors";
import {
  DEFAULT_FORM,
  formFromEnvironment,
  formProblem,
  LIMITS,
  toEnvironmentIn,
  type EnvironmentFormState,
  type EraKind,
} from "./environmentLabView";

type EnvironmentFormProps = {
  /** The environment to edit, or null to make a new one. */
  environment: LibraryEnvironment | null;
  /** Called with the saved environment. `created` is true for a new one. */
  onSaved: (environment: LibraryEnvironment, created: boolean) => void;
};

function counter(text: string, limit: number): string {
  return `${text.length.toLocaleString()} of ${limit.toLocaleString()} characters.`;
}

/**
 * The profile of an environment: what the place is. Only the name and the description are
 * required. The description is what the reference picture is drawn from, so it describes the
 * place itself (its buildings or landscape, materials, colours and landmarks), with no people.
 */
export function EnvironmentForm({ environment, onSaved }: EnvironmentFormProps) {
  const [form, setForm] = useState<EnvironmentFormState>(() =>
    environment === null ? DEFAULT_FORM : formFromEnvironment(environment),
  );
  const create = useCreateEnvironment();
  const edit = useEditEnvironment();
  const saving = create.isPending || edit.isPending;
  const failure = create.isError ? create.error : edit.isError ? edit.error : null;
  const problem = formProblem(form);

  function update(changes: Partial<EnvironmentFormState>) {
    setForm((current) => ({ ...current, ...changes }));
  }

  function save() {
    const body = toEnvironmentIn(form);
    if (environment === null) {
      create.mutate(body, { onSuccess: (made) => onSaved(made, true) });
    } else {
      edit.mutate(
        { environmentId: environment.id, body },
        { onSuccess: (changed) => onSaved(changed, false) },
      );
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (problem === null && !saving) {
          save();
        }
      }}
    >
      <Stack gap="md">
        <TextInput
          label="Name"
          required
          value={form.name}
          onChange={(event) => update({ name: event.currentTarget.value })}
          description={counter(form.name, LIMITS.name)}
        />

        <Textarea
          label="Description"
          required
          description={`What the place looks like: the buildings or landscape, materials, colours and the details that make it this place. ${counter(form.description, LIMITS.description)}`}
          value={form.description}
          onChange={(event) => update({ description: event.currentTarget.value })}
          autosize
          minRows={4}
        />

        <Stack gap={4}>
          <Text size="sm" fw={500}>
            When is it set?
          </Text>
          <SegmentedControl
            value={form.eraKind}
            onChange={(value) => update({ eraKind: value as EraKind })}
            data={[
              { value: "present", label: "Present" },
              { value: "past", label: "Past" },
              { value: "future", label: "Future" },
            ]}
          />
        </Stack>
        <Group grow align="flex-start">
          {form.eraKind !== "present" && (
            <TextInput
              label={`Years in the ${form.eraKind}`}
              required
              inputMode="numeric"
              description={`From 1 to ${LIMITS.eraYearsMax.toLocaleString()}.`}
              value={form.eraYears}
              onChange={(event) => update({ eraYears: event.currentTarget.value })}
            />
          )}
          <TextInput
            label="Setting"
            description="Optional. For example: Victorian London, Edo-period Japan."
            value={form.eraSetting}
            onChange={(event) => update({ eraSetting: event.currentTarget.value })}
          />
        </Group>

        <Textarea
          label="Atmosphere"
          description={`Optional. Its usual mood and light. ${counter(form.atmosphere, LIMITS.atmosphere)}`}
          value={form.atmosphere}
          onChange={(event) => update({ atmosphere: event.currentTarget.value })}
          autosize
          minRows={2}
        />
        <Textarea
          label="Notes"
          description={`Optional. Anything else every picture of the place should keep. ${counter(form.notes, LIMITS.notes)}`}
          value={form.notes}
          onChange={(event) => update({ notes: event.currentTarget.value })}
          autosize
          minRows={2}
        />

        {environment !== null && (
          <Text size="xs" c="dimmed">
            A change makes a new version with no picture yet. The earlier version keeps its own
            picture. Make a new picture for the new version afterwards.
          </Text>
        )}

        <Stack gap={6} align="flex-start">
          <Button type="submit" loading={saving} disabled={problem !== null}>
            {environment === null ? "Save" : "Save changes"}
          </Button>
          {problem !== null && form.name.trim() !== "" && (
            <Alert color="yellow" p="xs">
              {problem}
            </Alert>
          )}
          {failure !== null && (
            <Alert color="red" p="xs" title="The environment was not saved">
              {describeError(failure)}
            </Alert>
          )}
        </Stack>
      </Stack>
    </form>
  );
}
