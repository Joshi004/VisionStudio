import { useState } from "react";
import { Alert, Badge, Button, Group, Paper, Select, Stack, Text, TextInput } from "@mantine/core";

import {
  EVIDENCE_KINDS,
  type EvidenceClaim,
  type EvidenceClaimEdit,
} from "../../api/evidenceClaims";
import { SoundbiteControls } from "./SoundbiteControls";

type Props = {
  claim: EvidenceClaim;
  active?: boolean;
  busy: boolean;
  onSelect?: () => void;
  onEdit: (edit: EvidenceClaimEdit) => void;
  onRemove: () => void;
};

/** One evidence claim: its words, where it came from, its kind, note and sound bite settings. */
export function EvidenceClaimCard({ claim, active = false, busy, onSelect, onEdit, onRemove }: Props) {
  const [hint, setHint] = useState(claim.hint);
  const isOwner = claim.origin === "owner";
  const dropped = claim.kept === false;
  return (
    <Paper
      withBorder
      p="sm"
      radius="sm"
      onClick={onSelect}
      style={{ borderColor: active ? "var(--mantine-color-blue-filled)" : undefined }}
    >
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <Badge color={isOwner ? "teal" : "blue"} variant="light">
              {isOwner ? "You" : "GLM"}
            </Badge>
            {claim.origin === "glm" && claim.kept === null && (
              <Badge color="gray" variant="outline">
                To decide
              </Badge>
            )}
            {dropped && (
              <Badge color="gray" variant="outline">
                Dropped
              </Badge>
            )}
            {claim.want === "soundbite" && !dropped && (
              <Badge color="grape" variant="light">
                {claim.want_by === "glm" ? "Sound bite · GLM" : "Sound bite"}
              </Badge>
            )}
            <Text size="sm" fw={500} style={{ whiteSpace: "pre-wrap" }}>
              {claim.text}
            </Text>
          </Group>
          <Group gap="xs" wrap="nowrap">
            {isOwner ? (
              <Button size="compact-sm" variant="default" onClick={onRemove} disabled={busy}>
                Remove
              </Button>
            ) : (
              <>
                {claim.kept !== true && (
                  <Button
                    size="compact-sm"
                    onClick={() => onEdit({ kept: true })}
                    disabled={busy || claim.words_changed}
                  >
                    {dropped ? "Keep again" : "Keep"}
                  </Button>
                )}
                {claim.kept !== false && (
                  <Button
                    size="compact-sm"
                    variant="default"
                    onClick={() => onEdit({ kept: false })}
                    disabled={busy}
                  >
                    Drop
                  </Button>
                )}
              </>
            )}
          </Group>
        </Group>
        {claim.reason !== "" && (
          <Text size="xs" c="dimmed">
            {claim.reason}
          </Text>
        )}
        {claim.want === "soundbite" && claim.kept === null && !dropped && (
          <Text size="xs" c="dimmed">
            GLM chose this as a sound bite{claim.speaker ? `, said by ${claim.speaker}` : ""}. Keep
            the claim to change the speaker or make it ordinary evidence.
          </Text>
        )}
        {claim.words_changed && !dropped && (
          <Alert color="yellow" p="xs">
            {isOwner
              ? "The words of this claim are no longer in the story. Remove it and mark the new words."
              : "The words of this proposal are no longer in the story. Drop it."}
          </Alert>
        )}
        {!dropped && (
          <Group gap="xs" wrap="nowrap" onClick={(event) => event.stopPropagation()}>
            <Select
              size="xs"
              w={130}
              aria-label="Kind of claim"
              data={EVIDENCE_KINDS.map((kind) => ({ value: kind.value, label: kind.label }))}
              value={claim.kind_hint}
              allowDeselect={false}
              disabled={busy}
              onChange={(value) => {
                const kind = EVIDENCE_KINDS.find((item) => item.value === value);
                if (kind && kind.value !== claim.kind_hint) {
                  onEdit({ kind_hint: kind.value });
                }
              }}
            />
            <TextInput
              size="xs"
              style={{ flex: 1 }}
              aria-label="Note for the research (for example: must be the SEC filing)"
              placeholder="Note for the research (optional)"
              maxLength={300}
              value={hint}
              disabled={busy}
              onChange={(event) => setHint(event.currentTarget.value)}
              onBlur={() => {
                if (hint !== claim.hint) {
                  onEdit({ hint });
                }
              }}
            />
          </Group>
        )}
        {!dropped && !claim.words_changed && claim.kept !== null && (
          <SoundbiteControls claim={claim} busy={busy} onEdit={onEdit} />
        )}
      </Stack>
    </Paper>
  );
}
