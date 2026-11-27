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
import { FOOTAGE_KINDS, type FootageKind } from "../../api/footageMarks";
import type { StorySelection } from "./storyMarks";

export type MarkAction = "evidence" | "graphic" | "both" | "footage";

/** The settings of the evidence part of a mark. `kind` is null when it is left to the backend. */
export type EvidenceOptions = { hint: string; kind: EvidenceKind | null };

/** The settings of a footage mark: what the viewer should see (may be empty) and the kind. */
export type FootageOptions = { note: string; kind: FootageKind };

const NO_FOOTAGE: FootageOptions = { note: "", kind: "any" };

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
  /** The project has footage on, so the selection can be marked as footage. */
  canFootage: boolean;
  /** Why the selection cannot be marked as evidence (for example it overlaps your own claim). */
  evidenceBlockedReason: string | null;
  /** Why the selection cannot be marked as footage (it overlaps footage you already marked). */
  footageBlockedReason: string | null;
  busy: boolean;
  onMark: (action: MarkAction, options: EvidenceOptions, footage: FootageOptions) => void;
  onCancel: () => void;
};

/**
 * The small bar above the selected words: Evidence, Graphic, Both or Footage. Shortcuts: E, G, B,
 * F (opens the footage row, where the note and the kind are chosen), and Escape to drop the
 * selection. The rest of the page keeps the selection while a button is
 * pressed, because the bar stops the click from moving focus.
 */
export function SelectionToolbar({
  selection,
  canEvidence,
  canGraphic,
  canFootage,
  evidenceBlockedReason,
  footageBlockedReason,
  busy,
  onMark,
  onCancel,
}: Props) {
  const [showMore, setShowMore] = useState(false);
  const [hint, setHint] = useState("");
  const [kind, setKind] = useState<string>(AUTOMATIC);
  const [showFootage, setShowFootage] = useState(false);
  const [footageNote, setFootageNote] = useState("");
  const [footageKind, setFootageKind] = useState<FootageKind>("any");

  const evidenceOk = canEvidence && evidenceBlockedReason === null && !busy;
  const graphicOk = canGraphic && !busy;
  const bothOk = canEvidence && canGraphic && evidenceOk && graphicOk;
  const footageOk = canFootage && footageBlockedReason === null && !busy;

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
        onMark("evidence", options, NO_FOOTAGE);
      } else if (key === "g" && graphicOk) {
        event.preventDefault();
        onMark("graphic", options, NO_FOOTAGE);
      } else if (key === "b" && bothOk) {
        event.preventDefault();
        onMark("both", options, NO_FOOTAGE);
      } else if (key === "f" && footageOk) {
        event.preventDefault();
        setShowFootage(true);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [evidenceOk, graphicOk, bothOk, footageOk, hint, kind, onMark, onCancel]);

  function markFootage() {
    if (footageOk) {
      onMark("footage", evidenceOptions("", AUTOMATIC), { note: footageNote, kind: footageKind });
    }
  }

  const { rect } = selection;
  // Scrolled out of the window: nothing to point at.
  if (rect.top + rect.height < 0 || rect.top > window.innerHeight) {
    return null;
  }
  const rows = (showMore ? 1 : 0) + (showFootage ? 1 : 0);
  const below = rect.top < BAR_HEIGHT + rows * BAR_HEIGHT + GAP;
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
                  onClick={() => onMark("evidence", evidenceOptions(hint, kind), NO_FOOTAGE)}
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
              onClick={() => onMark("graphic", evidenceOptions(hint, kind), NO_FOOTAGE)}
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
                  onClick={() => onMark("both", evidenceOptions(hint, kind), NO_FOOTAGE)}
                  rightSection={<Kbd size="xs">B</Kbd>}
                >
                  Both
                </Button>
              </Box>
            </Tooltip>
          )}
          {canFootage && (
            <Tooltip label={footageBlockedReason} disabled={footageBlockedReason === null}>
              <Box component="span">
                <Button
                  size="compact-sm"
                  color="orange"
                  variant={showFootage ? "filled" : "light"}
                  disabled={!footageOk}
                  onClick={() => setShowFootage((open) => !open)}
                  rightSection={<Kbd size="xs">F</Kbd>}
                >
                  Footage
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
        {canFootage && showFootage && (
          <Group gap={6} mt={6} wrap="nowrap" align="flex-end">
            <NativeSelect
              size="xs"
              w={110}
              aria-label="Kind of footage"
              data={FOOTAGE_KINDS.map((item) => ({ value: item.value, label: item.label }))}
              value={footageKind}
              onChange={(event) => {
                const chosen = FOOTAGE_KINDS.find((item) => item.value === event.currentTarget.value);
                setFootageKind(chosen ? chosen.value : "any");
              }}
            />
            <TextInput
              size="xs"
              w={260}
              autoFocus
              aria-label="What should the viewer see?"
              placeholder="What should the viewer see? (optional)"
              maxLength={300}
              value={footageNote}
              onChange={(event) => setFootageNote(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  markFootage();
                }
              }}
            />
            <Button size="compact-sm" color="orange" disabled={!footageOk} onClick={markFootage}>
              Mark footage
            </Button>
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
