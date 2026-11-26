import { useState } from "react";

import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Switch,
  Text,
  Title,
} from "@mantine/core";

import { describeError } from "../../api/errors";
import {
  useEvidenceReview,
  useFinishEvidenceReview,
  useSaveEvidenceClaimDecision,
  useStartEvidencePreview,
  type EvidenceClaimDecision,
  type EvidenceReviewClaim,
  type EvidenceReviewItem,
  type SoundbiteDecision,
} from "../../api/evidence";
import { EvidencePreview, ReadabilityWarning } from "./EvidencePreview";
import { SoundbiteClipPanel, type ClipClaim, type CutWords } from "./SoundbiteClipPanel";
import { CLAIM_STATUS_COLOR, CLAIM_STATUS_LABEL } from "./evidenceLabels";

type EvidenceReviewProps = {
  projectId: number;
};

const RELATION_LABEL: Record<string, string> = {
  supports: "Supports",
  partly_supports: "Partly supports",
  contradicts: "Contradicts",
  context: "Context",
};

const RELATION_COLOR: Record<string, string> = {
  supports: "green",
  partly_supports: "yellow",
  contradicts: "red",
  context: "gray",
};

const TIER_LABEL: Record<string, string> = {
  primary: "Primary source",
  secondary: "Secondary source",
  other: "Other source",
};

const HIGHLIGHT_STYLE = {
  position: "absolute",
  boxSizing: "border-box",
  backgroundColor: "rgba(255, 212, 59, 0.35)",
  pointerEvents: "none",
} as const;

/** The agent's addresses are shown as links only when they are plain http or https. */
function safeHref(value: string | null): string | null {
  return value !== null && /^https?:\/\//i.test(value) ? value : null;
}

function percent(value: number): string {
  return `${value * 100}%`;
}

/**
 * The clean screenshot with the quote's rectangles drawn over it. The boxes are fractions of the
 * image, so they follow the displayed size.
 */
function HighlightedImage({
  url,
  rects,
  alt,
  maxHeight,
}: {
  url: string;
  rects: number[][];
  alt: string;
  maxHeight: number;
}) {
  return (
    <div style={{ position: "relative", display: "inline-block", lineHeight: 0 }}>
      <img
        src={url}
        alt={alt}
        loading="lazy"
        style={{ display: "block", maxWidth: "100%", maxHeight }}
      />
      {rects.map((rect, index) => (
        <div
          key={index}
          style={{
            ...HIGHLIGHT_STYLE,
            left: percent(rect[0]),
            top: percent(rect[1]),
            width: percent(rect[2]),
            height: percent(rect[3]),
          }}
        />
      ))}
    </div>
  );
}

function SourceLine({ item }: { item: EvidenceReviewItem }) {
  const source = item.source;
  if (source === null) {
    return null;
  }
  const url = safeHref(source.final_url) ?? safeHref(source.url);
  const archive = safeHref(source.archive_url);
  const name = source.title ?? source.publisher ?? "Source";
  return (
    <Group gap="xs">
      <Text size="sm">
        {source.publisher !== null && source.title !== null ? `${source.publisher}: ` : ""}
        {url !== null ? (
          <a href={url} target="_blank" rel="noopener noreferrer">
            {name}
          </a>
        ) : (
          name
        )}
        {source.published !== null ? `, ${source.published}` : ""}
        {item.page !== null ? `, page ${item.page}` : ""}
      </Text>
      {archive !== null && (
        <Text size="sm">
          <a href={archive} target="_blank" rel="noopener noreferrer">
            Archive copy
          </a>
        </Text>
      )}
    </Group>
  );
}

type PieceProps = {
  projectId: number;
  item: EvidenceReviewItem;
  // The claim a video belongs to: a clip of a sound bite claim is decided in its own panel.
  clipClaim: ClipClaim;
  shown: boolean;
  disabled: boolean;
  onVerdict: (verdict: "accepted" | "rejected") => void;
  onAcceptClip: (cut?: CutWords) => void;
  onShown: (shown: boolean) => void;
  previewStarting: boolean;
  onPreview: () => void;
};

function PieceCard({
  projectId,
  item,
  clipClaim,
  shown,
  disabled,
  onVerdict,
  onAcceptClip,
  onShown,
  previewStarting,
  onPreview,
}: PieceProps) {
  const [contextOpen, setContextOpen] = useState(false);
  const isClip = item.kind === "video";
  // A clip of a sound bite claim has its own Accept and Reject; any other video is context.
  const isBite = isClip && clipClaim.want === "soundbite";
  // A video of a claim that is not a sound bite is never shown on video.
  const canShow = !isClip || isBite;
  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap="xs">
        <Group gap="xs">
          <Text size="sm" fw={600}>
            {item.evidence_id}
          </Text>
          {item.relation !== null && (
            <Badge size="sm" variant="light" color={RELATION_COLOR[item.relation] ?? "gray"}>
              {RELATION_LABEL[item.relation] ?? item.relation}
            </Badge>
          )}
          {item.source_tier !== null && (
            <Badge size="sm" variant="outline" color="gray">
              {TIER_LABEL[item.source_tier] ?? item.source_tier}
            </Badge>
          )}
          {item.usable && item.verdict === null && (
            <Badge size="sm" color="yellow" variant="light">
              Undecided
            </Badge>
          )}
          {item.verdict === "accepted" && (
            <Badge size="sm" color="green" variant="filled">
              Accepted
            </Badge>
          )}
          {item.verdict === "rejected" && (
            <Badge size="sm" color="gray" variant="filled">
              Rejected
            </Badge>
          )}
        </Group>

        {!item.usable && (
          <Stack gap={2}>
            <Text size="sm" c="red" fw={600}>
              This piece cannot be used.
            </Text>
            {item.reasons.map((text) => (
              <Text key={text} size="xs" c="red">
                {text}
              </Text>
            ))}
          </Stack>
        )}

        {item.usable && item.image_url !== null && (
          <Stack gap={4} align="flex-start">
            <HighlightedImage
              url={item.image_url}
              rects={item.rects}
              alt={`Screenshot of the evidence ${item.evidence_id}`}
              maxHeight={360}
            />
            {item.context_url !== null && (
              <Button size="compact-xs" variant="subtle" onClick={() => setContextOpen(true)}>
                Show context
              </Button>
            )}
          </Stack>
        )}

        {item.quote !== null && (
          <Text size="sm" style={{ fontStyle: "italic" }}>
            &ldquo;{item.quote}&rdquo;
          </Text>
        )}
        <SourceLine item={item} />
        {item.what_it_says !== null && <Text size="sm">{item.what_it_says}</Text>}
        {item.agent_notes !== null && item.agent_notes !== "" && (
          <Text size="xs" c="dimmed">
            Agent&apos;s notes: {item.agent_notes}
          </Text>
        )}
        {item.relation === "contradicts" && (
          <Alert color="red" p="xs">
            This source says otherwise than the claim. Show it on video only if that is what you
            want to say.
          </Alert>
        )}
        {item.warnings.map((text) => (
          <Text key={text} size="xs" c="orange">
            {text}
          </Text>
        ))}

        <ReadabilityWarning item={item} />

        {isClip && (
          <SoundbiteClipPanel
            item={item}
            projectId={projectId}
            claim={clipClaim}
            disabled={disabled}
            onAccept={onAcceptClip}
            onReject={() => onVerdict("rejected")}
          />
        )}

        {item.usable && isBite && item.verdict === "accepted" && (
          <Checkbox
            size="xs"
            label="Show on video"
            checked={shown}
            disabled={disabled}
            onChange={(event) => onShown(event.currentTarget.checked)}
          />
        )}

        {item.usable && !isBite && (
          <Group gap="sm">
            <Button
              size="xs"
              color="green"
              variant={item.verdict === "accepted" ? "filled" : "light"}
              disabled={disabled}
              onClick={() => onVerdict("accepted")}
            >
              Accept
            </Button>
            <Button
              size="xs"
              color="gray"
              variant={item.verdict === "rejected" ? "filled" : "light"}
              disabled={disabled}
              onClick={() => onVerdict("rejected")}
            >
              Reject
            </Button>
            {item.verdict === "accepted" && canShow && (
              <Checkbox
                size="xs"
                label="Show on video"
                checked={shown}
                disabled={disabled}
                onChange={(event) => onShown(event.currentTarget.checked)}
              />
            )}
          </Group>
        )}

        {item.usable && (!isClip || isBite) && item.verdict === "accepted" && (
          <EvidencePreview
            item={item}
            disabled={disabled}
            starting={previewStarting}
            onStart={onPreview}
          />
        )}
      </Stack>

      {item.context_url !== null && (
        <Modal
          opened={contextOpen}
          onClose={() => setContextOpen(false)}
          title={`Context of ${item.evidence_id}`}
          size="xl"
        >
          <div style={{ position: "relative", display: "inline-block", lineHeight: 0 }}>
            <img
              src={item.context_url}
              alt={`Context around the evidence ${item.evidence_id}`}
              style={{ display: "block", maxWidth: "100%" }}
            />
            {item.context_box !== null && (
              <div
                style={{
                  ...HIGHLIGHT_STYLE,
                  border: "2px solid #f08c00",
                  backgroundColor: "transparent",
                  left: percent(item.context_box[0]),
                  top: percent(item.context_box[1]),
                  width: percent(item.context_box[2]),
                  height: percent(item.context_box[3]),
                }}
              />
            )}
          </div>
        </Modal>
      )}
    </Paper>
  );
}

function decisionOf(claim: EvidenceReviewClaim): EvidenceClaimDecision {
  return {
    items: claim.items.flatMap((item) => {
      if (!item.usable || item.verdict === null) {
        return [];
      }
      // A PUT replaces the whole decision, so an accepted clip sends its details back as they
      // are saved (the cut is found again by the server only when the words change).
      const saved = item.verdict === "accepted" ? item.soundbite?.decision : null;
      return [
        {
          item_key: item.item_key,
          verdict: item.verdict,
          ...(saved != null
            ? {
                soundbite: {
                  first_word: saved.first_word,
                  last_word: saved.last_word,
                  speaker: saved.speaker,
                  role: saved.role,
                  venue: saved.venue,
                  recorded: saved.recorded,
                  acknowledged_flags: saved.acknowledged_flags,
                  rights_note: saved.rights_note,
                  music_drop: saved.music_drop,
                },
              }
            : {}),
        },
      ];
    }),
    shown: claim.shown,
    no_proof_on_screen: claim.no_proof_on_screen,
  };
}

function ClaimCard({
  projectId,
  claim,
  editable,
  saving,
  onSave,
  previewingKey,
  onPreview,
}: {
  projectId: number;
  claim: EvidenceReviewClaim;
  editable: boolean;
  saving: boolean;
  onSave: (claimId: string, decision: EvidenceClaimDecision) => void;
  previewingKey: string | null;
  onPreview: (itemKey: string) => void;
}) {
  const key = claim.status ?? claim.result_state;
  const disabled = !editable || saving;
  const isBiteClaim = claim.want === "soundbite";
  const clipClaim: ClipClaim = { want: claim.want, speaker: claim.speaker };
  // The pieces that can be shown: not a video of a claim that is not a sound bite.
  const showable = claim.items.filter(
    (item) => item.usable && (item.kind !== "video" || isBiteClaim),
  );
  const save = (decision: EvidenceClaimDecision) => onSave(claim.claim_id, decision);

  const isClipKey = (itemKey: string) =>
    claim.items.some((item) => item.item_key === itemKey && item.kind === "video");

  // What shows on video once `itemKey` is shown: a sound bite clip is shown alone, and nothing
  // is shown beside it (the server refuses both).
  const withShown = (current: string[], itemKey: string): string[] => {
    const others = current.filter((entry) => entry !== itemKey);
    if (isClipKey(itemKey)) {
      return [itemKey];
    }
    return [...others.filter((entry) => !isClipKey(entry)), itemKey];
  };

  const setVerdict = (
    itemKey: string,
    verdict: "accepted" | "rejected",
    soundbite?: SoundbiteDecision,
    cut?: CutWords,
  ) => {
    const current = decisionOf(claim);
    const item = claim.items.find((entry) => entry.item_key === itemKey);
    // A cut is only the owner's words: the server finds the times and fills in the details.
    const items = [
      ...current.items.filter((entry) => entry.item_key !== itemKey),
      {
        item_key: itemKey,
        verdict,
        ...(soundbite !== undefined ? { soundbite } : {}),
        ...(cut !== undefined ? { cut } : {}),
      },
    ];
    const others = current.shown.filter((entry) => entry !== itemKey);
    // An accepted piece is shown by default; the owner can untick it. Saving new details of a
    // clip that is already accepted keeps it as it was shown or not. A video that is only
    // context is never shown, and a web page or PDF accepted beside a shown clip is not shown.
    const wasAccepted = item?.verdict === "accepted";
    const showNow =
      verdict === "accepted" &&
      (item?.kind !== "video" || isBiteClaim) &&
      (wasAccepted ? current.shown.includes(itemKey) : true) &&
      (isClipKey(itemKey) || !others.some(isClipKey));
    const shown = showNow ? withShown(current.shown, itemKey) : others;
    save({ items, shown, no_proof_on_screen: shown.length > 0 ? false : current.no_proof_on_screen });
  };

  const setShown = (itemKey: string, on: boolean) => {
    const current = decisionOf(claim);
    save({
      ...current,
      shown: on ? withShown(current.shown, itemKey) : current.shown.filter((e) => e !== itemKey),
      no_proof_on_screen: on ? false : current.no_proof_on_screen,
    });
  };

  const move = (itemKey: string, step: -1 | 1) => {
    const current = decisionOf(claim);
    const from = current.shown.indexOf(itemKey);
    const to = from + step;
    if (from < 0 || to < 0 || to >= current.shown.length) {
      return;
    }
    const shown = [...current.shown];
    [shown[from], shown[to]] = [shown[to], shown[from]];
    save({ ...current, shown });
  };

  const setNoProof = (on: boolean) => {
    const current = decisionOf(claim);
    save({ ...current, shown: on ? [] : current.shown, no_proof_on_screen: on });
  };

  const idOf = (itemKey: string) =>
    claim.items.find((item) => item.item_key === itemKey)?.evidence_id ?? itemKey;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group gap="xs">
          <Text fw={700}>{claim.claim_id}</Text>
          <Badge size="sm" variant="outline" color="gray">
            {claim.origin === "owner" ? "Your mark" : "Proposed by GLM"}
          </Badge>
          <Badge size="sm" variant="light" color={CLAIM_STATUS_COLOR[key] ?? "gray"}>
            {CLAIM_STATUS_LABEL[key] ?? key}
          </Badge>
          {isBiteClaim && (
            <Badge size="sm" variant="filled" color="grape">
              Sound bite{claim.speaker !== null ? `: ${claim.speaker}` : ""}
            </Badge>
          )}
          {claim.decided ? (
            <Badge size="sm" variant="light" color="green">
              Decided
            </Badge>
          ) : (
            <Badge size="sm" variant="light" color="yellow">
              Undecided
            </Badge>
          )}
        </Group>

        <Text size="sm" fw={600}>
          &ldquo;{claim.text}&rdquo;
        </Text>
        <Text size="xs" c="dimmed">
          {claim.sentence}
        </Text>
        {claim.hint !== "" && (
          <Text size="xs" c="dimmed">
            Your note: {claim.hint}
          </Text>
        )}
        {claim.summary !== "" && <Text size="sm">{claim.summary}</Text>}

        {claim.status === "contradicted" && (
          <Alert color="red" title="The sources say otherwise">
            The script may be wrong here. Check it before you show this claim.
          </Alert>
        )}
        {claim.problems.map((text) => (
          <Text key={`p-${text}`} size="xs" c="red">
            {text}
          </Text>
        ))}
        {claim.warnings.map((text) => (
          <Text key={`w-${text}`} size="xs" c="orange">
            {text}
          </Text>
        ))}

        {(claim.status === "not_found" || claim.status === "blocked") &&
          claim.attempts.length > 0 && (
            <Stack gap={2}>
              <Text size="xs" fw={600}>
                What was tried
              </Text>
              {claim.attempts.map((attempt, index) => (
                <Text key={index} size="xs" c="dimmed">
                  {attempt.what}: {attempt.outcome}
                </Text>
              ))}
            </Stack>
          )}

        {claim.items.map((item) => (
          <PieceCard
            key={item.item_key}
            projectId={projectId}
            item={item}
            clipClaim={clipClaim}
            shown={claim.shown.includes(item.item_key)}
            disabled={disabled}
            onVerdict={(verdict) => setVerdict(item.item_key, verdict)}
            onAcceptClip={(cut) => setVerdict(item.item_key, "accepted", undefined, cut)}
            onShown={(on) => setShown(item.item_key, on)}
            previewStarting={previewingKey === item.item_key}
            onPreview={() => onPreview(item.item_key)}
          />
        ))}

        {claim.shown.length > 1 && (
          <Stack gap={4}>
            <Text size="xs" fw={600}>
              Shown on video, in this order
            </Text>
            {claim.shown.map((itemKey, index) => (
              <Group key={itemKey} gap="xs">
                <Text size="sm">
                  {index + 1}. {idOf(itemKey)}
                </Text>
                <Button
                  size="compact-xs"
                  variant="subtle"
                  disabled={disabled || index === 0}
                  onClick={() => move(itemKey, -1)}
                >
                  Up
                </Button>
                <Button
                  size="compact-xs"
                  variant="subtle"
                  disabled={disabled || index === claim.shown.length - 1}
                  onClick={() => move(itemKey, 1)}
                >
                  Down
                </Button>
              </Group>
            ))}
          </Stack>
        )}

        <Switch
          label="No proof on screen"
          description={
            showable.length === 0
              ? "This claim has no usable evidence to show. It stays in the script without an evidence shot."
              : isBiteClaim
                ? "No clip plays for this claim: the narrator reads the quote, even if a piece is accepted."
                : "The claim stays in the script without an evidence shot, even if a piece is accepted."
          }
          checked={claim.no_proof_on_screen}
          disabled={disabled}
          onChange={(event) => setNoProof(event.currentTarget.checked)}
        />
      </Stack>
    </Paper>
  );
}

/**
 * The owner's review of the newest import: one card per claim with its checked evidence, a
 * verdict for each usable piece, what is shown on video, and "Review done". Every change is saved
 * at once. Everything the agent wrote is shown as plain text.
 */
export function EvidenceReview({ projectId }: EvidenceReviewProps) {
  const { data, isLoading, isError, error } = useEvidenceReview(projectId);
  const save = useSaveEvidenceClaimDecision(projectId);
  const finish = useFinishEvidenceReview(projectId);
  const preview = useStartEvidencePreview(projectId);

  const onSave = (claimId: string, decision: EvidenceClaimDecision) =>
    save.mutate({ claimId, decision });

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="center">
        <Title order={5}>Review the evidence</Title>
        {data?.done === true && (
          <Badge color="green" variant="light">
            Review done
          </Badge>
        )}
      </Group>
      <Text size="xs" c="dimmed">
        Nothing reaches the video without your acceptance. Decide every claim, then press Review
        done. Changing a decision afterwards takes the review back until you press it again. Claims
        reviewed in an earlier round are kept as they were and are not listed here.
      </Text>

      {isLoading && <Loader size="sm" />}
      {isError && (
        <Alert color="red" title="Could not load the review">
          {describeError(error)}
        </Alert>
      )}
      {data !== undefined && data.blocked_reason !== null && (
        <Alert color="gray">{data.blocked_reason}</Alert>
      )}

      {data?.claims.map((claim) => (
        <ClaimCard
          projectId={projectId}
          key={claim.claim_id}
          claim={claim}
          editable={data.editable}
          saving={save.isPending}
          onSave={onSave}
          previewingKey={preview.isPending ? preview.variables : null}
          onPreview={(itemKey) => preview.mutate(itemKey)}
        />
      ))}

      {save.isError && (
        <Alert color="red" title="Could not save the decision">
          {describeError(save.error)}
        </Alert>
      )}

      {preview.isError && (
        <Alert color="red" title="Could not start the preview">
          {describeError(preview.error)}
        </Alert>
      )}

      {data !== undefined && data.claims.length > 0 && (
        <Group justify="space-between" align="center">
          <Text size="sm" c={data.undecided.length > 0 ? "orange" : "dimmed"}>
            {data.undecided.length > 0
              ? `Still to decide: ${data.undecided.join(", ")}`
              : "Every claim is decided."}
          </Text>
          <Button
            onClick={() => finish.mutate()}
            loading={finish.isPending}
            disabled={!data.editable || data.undecided.length > 0 || data.done}
          >
            Review done
          </Button>
        </Group>
      )}
      {finish.isError && (
        <Alert color="red" title="Could not finish the review">
          {describeError(finish.error)}
        </Alert>
      )}
    </Stack>
  );
}
