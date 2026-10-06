import { useState } from "react";
import { Alert, Button, Group, Modal, Radio, Stack, Text, TextInput } from "@mantine/core";
import { useNavigate } from "react-router";

import { describeError } from "../../api/errors";
import { useCreateProject } from "../../api/projects";

const ORIENTATIONS = [
  { value: "landscape", label: "Landscape", size: "1920 x 1080" },
  { value: "portrait", label: "Portrait", size: "1080 x 1920" },
] as const;

type Orientation = (typeof ORIENTATIONS)[number]["value"];

function isOrientation(value: string): value is Orientation {
  return ORIENTATIONS.some((option) => option.value === value);
}

/** Lives inside the modal, so closing the modal throws the form state away. */
function CreateProjectForm({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const create = useCreateProject();
  const [orientation, setOrientation] = useState<Orientation | null>(null);
  const [name, setName] = useState("");

  const canCreate = orientation !== null && name.trim() !== "";

  function submit() {
    if (orientation === null) {
      return;
    }
    create.mutate(
      { name, orientation },
      {
        onSuccess: (project) => {
          onClose();
          void navigate(`/projects/${project.id}`);
        },
      },
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (canCreate) {
          submit();
        }
      }}
    >
      <Stack gap="md">
        <Radio.Group
          label="1. Orientation"
          description="Choose this first. It sets the video size and cannot be changed later."
          value={orientation ?? ""}
          onChange={(value) => {
            if (isOrientation(value)) {
              setOrientation(value);
            }
          }}
        >
          <Group mt="xs" grow align="stretch">
            {ORIENTATIONS.map((option) => (
              <Radio.Card key={option.value} value={option.value} p="md" radius="md">
                <Group wrap="nowrap" align="flex-start">
                  <Radio.Indicator />
                  <Stack gap={2}>
                    <Text fw={500}>{option.label}</Text>
                    <Text size="sm" c="dimmed">
                      {option.size}
                    </Text>
                  </Stack>
                </Group>
              </Radio.Card>
            ))}
          </Group>
        </Radio.Group>

        <TextInput
          label="2. Name"
          value={name}
          onChange={(event) => setName(event.currentTarget.value)}
          maxLength={200}
          data-autofocus
        />

        {create.isError && <Alert color="red">{describeError(create.error)}</Alert>}

        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button type="submit" disabled={!canCreate} loading={create.isPending}>
            Create project
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function CreateProjectModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  return (
    <Modal opened={opened} onClose={onClose} title="New project" centered>
      <CreateProjectForm onClose={onClose} />
    </Modal>
  );
}
