import { useState } from "react";
import { Alert, Button, Group, Stack, Text, TextInput } from "@mantine/core";

import type { EvidenceClaim, EvidenceClaimEdit } from "../../api/evidenceClaims";

type Props = {
  claim: EvidenceClaim;
  busy: boolean;
  onEdit: (edit: EvidenceClaimEdit) => void;
};

/**
 * Makes a claim a sound bite (a clip of the person saying the quote) and shows whether the
 * script around it will work. The quote must be whole sentences in quotation marks; the other
 * script rules are warnings that never block anything.
 */
export function SoundbiteControls({ claim, busy, onEdit }: Props) {
  const [speaker, setSpeaker] = useState(claim.speaker ?? "");
  const isSoundbite = claim.want === "soundbite";
  const block = claim.soundbite_block;

  if (!isSoundbite) {
    const canMake = speaker.trim() !== "" && block === null;
    return (
      <Stack gap={4} onClick={(event) => event.stopPropagation()}>
        <Group gap="xs" wrap="nowrap">
          <TextInput
            size="xs"
            style={{ flex: 1 }}
            aria-label="Who says the quote"
            placeholder="Who says it (for a sound bite)"
            maxLength={100}
            value={speaker}
            disabled={busy}
            onChange={(event) => setSpeaker(event.currentTarget.value)}
          />
          <Button
            size="compact-sm"
            variant="default"
            disabled={busy || !canMake}
            title={block ?? undefined}
            onClick={() => onEdit({ want: "soundbite", speaker: speaker.trim() })}
          >
            Make sound bite
          </Button>
        </Group>
        {block !== null && claim.kind_hint === "quote" && (
          <Text size="xs" c="dimmed">
            {block}
          </Text>
        )}
      </Stack>
    );
  }

  return (
    <Stack gap={6} onClick={(event) => event.stopPropagation()}>
      <Group gap="xs" wrap="nowrap">
        <TextInput
          size="xs"
          style={{ flex: 1 }}
          aria-label="Who says the quote"
          maxLength={100}
          value={speaker}
          disabled={busy}
          onChange={(event) => setSpeaker(event.currentTarget.value)}
          onBlur={() => {
            const name = speaker.trim();
            if (name === "") {
              setSpeaker(claim.speaker ?? "");
            } else if (name !== claim.speaker) {
              onEdit({ speaker: name });
            }
          }}
        />
        <Button
          size="compact-sm"
          variant="default"
          disabled={busy}
          onClick={() => {
            setSpeaker("");
            onEdit({ want: "evidence" });
          }}
        >
          Make ordinary evidence
        </Button>
      </Group>
      {block !== null && (
        <Alert color="red" p="xs" title="This is no longer a quote that can be cut out">
          {block} The research brief waits until you fix the story or make this ordinary evidence.
        </Alert>
      )}
      {claim.soundbite_warnings.length > 0 && (
        <Alert color="yellow" p="xs" title="The script around the quote">
          <Stack gap={4}>
            {claim.soundbite_warnings.map((warning) => (
              <Text size="xs" key={warning.code}>
                {warning.message}
                {warning.words.length > 0 && ` (${warning.words.map((w) => `"${w}"`).join(", ")})`}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}
      {claim.soundbite_hints.map((hint) => (
        <Text size="xs" c="dimmed" key={hint}>
          {hint}
        </Text>
      ))}
      <Text size="xs" c="dimmed">
        The sentence after the quote should add something: it may echo one word, never restate
        the clip.
      </Text>
    </Stack>
  );
}
