import { useEffect, useState, type MouseEvent } from "react";
import {
  Box,
  Button,
  Group,
  Kbd,
  NativeSelect,
  Paper,
  Portal,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";

import { EVIDENCE_KINDS, type EvidenceKind } from "../../api/evidenceClaims";
import type { StorySelection } from "./storyMarks";

export type MarkAction = "evidence" | "graphic" | "both";

/** The settings of the evidence part of a mark. `kind` is null when it is left to the backend. */
export type EvidenceOptions = { hint: string; kind: EvidenceKind | null };

const AUTOMATIC = "auto";
const KIND_OPTIONS = [
  { value: AUTOMATIC, label: "Kind: automatic" },
  ...EVIDENCE_KINDS.map((kind) => ({ value: kind.value, label: kind.label })),
];

function evidenceOptions(hint: string, kind: string): EvidenceOptions {
  const chosen = EVIDENCE_KINDS.find((item) => item.value === kind);
  return { hint, kind: chosen ? chosen.value : null };
}

/** The toolbar's height and half width, to keep it inside the window. */
const BAR_HEIGHT = 56;
const BAR_HALF_WIDTH = 190;
const GAP = 8;

type Props = {
  selection: StorySelection;
  /** The project has evidence on, so the selection can be marked as a claim. */
  canEvidence: boolean;
  /** The project has graphics on, so the selection can be suggested as a graphic. */
  canGraphic: boolean;
  /** Why the selection cannot be marked as evidence (for example it overlaps your own claim). */
  evidenceBlockedReason: string | null;
  busy: boolean;
  onMark: (action: MarkAction, options: EvidenceOptions) => void;
  onCancel: () => void;
};

/**
 * The small bar above the selected words: Evidence, Graphic or Both. Shortcuts: E, G, B, and
 * Escape to drop the selection. The rest of the page keeps the selection while a button is
 * pressed, because the bar stops the click from moving focus.
 */
export function SelectionToolbar({
  selection,
  canEvidence,
  canGraphic,
  evidenceBlockedReason,
  busy,
  onMark,
  onCancel,
}: Props) {
  const [showMore, setShowMore] = useState(false);
  const [hint, setHint] = useState("");
  const [kind, setKind] = useState<string>(AUTOMATIC);

  const evidenceOk = canEvidence && evidenceBlockedReason === null && !busy;
  const graphicOk = canGraphic && !busy;
  const bothOk = canEvidence && canGraphic && evidenceOk && graphicOk;

  useEffect(() => {
    const options = evidenceOptions(hint, kind);
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target;
      if (
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement
      ) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key === "escape") {
        onCancel();
      } else if (key === "e" && evidenceOk) {
        event.preventDefault();
        onMark("evidence", options);
      } else if (key === "g" && graphicOk) {
        event.preventDefault();
        onMark("graphic", options);
      } else if (key === "b" && bothOk) {
        event.preventDefault();
        onMark("both", options);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [evidenceOk, graphicOk, bothOk, hint, kind, onMark, onCancel]);

  const { rect } = selection;
  // Scrolled out of the window: nothing to point at.
  if (rect.top + rect.height < 0 || rect.top > window.innerHeight) {
    return null;
  }
  const below = rect.top < BAR_HEIGHT + (showMore ? BAR_HEIGHT : 0) + GAP;
  const centre = Math.min(
    Math.max(rect.left + rect.width / 2, BAR_HALF_WIDTH),
    Math.max(window.innerWidth - BAR_HALF_WIDTH, BAR_HALF_WIDTH),
  );

  // Keep the selection when a button is pressed; a field or a list still needs its click.
  function keepSelection(event: MouseEvent) {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) {
      event.preventDefault();
    }
  }

  return (
    <Portal>
      <Paper
        withBorder
        shadow="md"
        p={6}
        radius="md"
        role="toolbar"
        aria-label="Mark the selected words"
        onMouseDown={keepSelection}
        style={{
          position: "fixed",
          zIndex: 400,
          left: centre,
          top: below ? rect.top + rect.height + GAP : rect.top - GAP,
          transform: below ? "translateX(-50%)" : "translate(-50%, -100%)",
        }}
      >
        <Group gap={6} wrap="nowrap">
          {canEvidence && (
            <Tooltip label={evidenceBlockedReason} disabled={evidenceBlockedReason === null}>
              <Box component="span">
                <Button
                  size="compact-sm"
                  color="teal"
                  disabled={!evidenceOk}
                  onClick={() => onMark("evidence", evidenceOptions(hint, kind))}
                  rightSection={<Kbd size="xs">E</Kbd>}
                >
                  Evidence
                </Button>
              </Box>
            </Tooltip>
          )}
          {canGraphic && (
            <Button
              size="compact-sm"
              color="yellow"
              disabled={!graphicOk}
              onClick={() => onMark("graphic", evidenceOptions(hint, kind))}
              rightSection={<Kbd size="xs">G</Kbd>}
            >
              Graphic
            </Button>
          )}
          {canEvidence && canGraphic && (
            <Tooltip label={evidenceBlockedReason} disabled={evidenceBlockedReason === null}>
              <Box component="span">
                <Button
                  size="compact-sm"
                  variant="light"
                  disabled={!bothOk}
                  onClick={() => onMark("both", evidenceOptions(hint, kind))}
                  rightSection={<Kbd size="xs">B</Kbd>}
                >
                  Both
                </Button>
              </Box>
            </Tooltip>
          )}
          {canEvidence && (
            <Button
              size="compact-sm"
              variant="subtle"
              color="gray"
              onClick={() => setShowMore((open) => !open)}
            >
              {showMore ? "Less" : "More"}
            </Button>
          )}
          <Button
            size="compact-sm"
            variant="subtle"
            color="gray"
            aria-label="Drop the selection"
            onClick={onCancel}
          >
            Esc
          </Button>
        </Group>
        {canEvidence && showMore && (
          <Group gap={6} mt={6} wrap="nowrap" align="flex-end">
            <NativeSelect
              size="xs"
              w={140}
              aria-label="Kind of claim"
              data={KIND_OPTIONS}
              value={kind}
              onChange={(event) => setKind(event.currentTarget.value)}
            />
            <TextInput
              size="xs"
              w={240}
              aria-label="Note for the research"
              placeholder="Note for the research (optional)"
              maxLength={300}
              value={hint}
              onChange={(event) => setHint(event.currentTarget.value)}
            />
          </Group>
        )}
        {showMore && (
          <Text size="xs" c="dimmed" mt={4}>
            The kind and the note are for the evidence part.
          </Text>
        )}
      </Paper>
    </Portal>
  );
}
