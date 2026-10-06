import { Fragment, useState } from "react";
import { Alert, Badge, Button, Group, Modal, ScrollArea, Stack, Text } from "@mantine/core";

import { ApiError, describeError } from "../../api/errors";
import type { ProjectDetail } from "../../api/projects";
import { useEditCut, type CutEditBody, type Scene, type SceneWord } from "../../api/scenes";
import classes from "./CutEditor.module.css";
import { cutsByWord, moveRange, sceneOfEachWord, scenesByFirstWord } from "./cutView";
import { isOutsideLimits, seconds } from "./sceneView";
import { groupByParagraph } from "./transcriptView";

const CUT_SOURCE: Record<Scene["cut_source"], { label: string; barClass: string }> = {
  ai: { label: "AI", barClass: classes.cutAi },
  rule: { label: "rule", barClass: classes.cutRule },
  manual: { label: "manual", barClass: classes.cutManual },
};

type NeedsConfirmation = { edit: CutEditBody; message: string };

function quoted(word: SceneWord | undefined): string {
  return word ? `\u201c${word.word}\u201d` : "";
}

/**
 * The script's words with a clickable gap between each two. Click a gap to add a cut. Click
 * a cut to pick it up, then click a highlighted gap to move it, or remove it. Every click
 * is one request, and the answer replaces the scenes on the page.
 */
export function CutEditor({
  project,
  scenes,
  words,
  onEdited,
}: {
  project: ProjectDetail;
  scenes: Scene[];
  words: SceneWord[];
  /** Called after an edit went through (scene times changed, so playback must stop). */
  onEdited: () => void;
}) {
  const editCut = useEditCut(project.id);
  const [picked, setPicked] = useState<number | null>(null);
  const [confirmation, setConfirmation] = useState<NeedsConfirmation | null>(null);

  const cuts = cutsByWord(scenes);
  const sceneStarts = scenesByFirstWord(scenes);
  const sceneOfWord = sceneOfEachWord(scenes, words.length);
  // The cut picked up, if it still exists (the scenes may have been loaded again meanwhile).
  const selected = picked !== null && cuts.has(picked) ? picked : null;
  const range = selected !== null ? moveRange(scenes, selected) : null;
  const busy = editCut.isPending;

  function send(edit: CutEditBody) {
    editCut.mutate(edit, {
      onSuccess: () => {
        setPicked(null);
        setConfirmation(null);
        onEdited();
      },
      onError: (error) => {
        // A scene beside the cut has inputs: ask, and send the same edit again if confirmed.
        if (error instanceof ApiError && error.status === 409) {
          setConfirmation({ edit, message: error.message });
        }
      },
    });
  }

  function clickGap(after: number) {
    if (cuts.has(after)) {
      setPicked(selected === after ? null : after);
    } else if (selected !== null) {
      send({
        action: "move",
        after_word: selected,
        to_after_word: after,
        discard_inputs: false,
      });
    } else {
      send({ action: "add", after_word: after, discard_inputs: false });
    }
  }

  function closeConfirmation() {
    setConfirmation(null);
    editCut.reset();
  }

  const failure =
    editCut.isError && !(editCut.error instanceof ApiError && editCut.error.status === 409)
      ? editCut.error
      : null;

  return (
    <Stack gap="xs">
      {selected !== null ? (
        <Group gap="sm">
          <Text size="sm">
            Moving the cut after {quoted(words[selected])}: click a highlighted gap, or
          </Text>
          <Button
            size="compact-sm"
            color="red"
            variant="light"
            disabled={busy}
            onClick={() =>
              send({ action: "remove", after_word: selected, discard_inputs: false })
            }
          >
            Remove this cut
          </Button>
          <Button
            size="compact-sm"
            variant="default"
            disabled={busy}
            onClick={() => setPicked(null)}
          >
            Cancel
          </Button>
        </Group>
      ) : (
        <Text size="sm" c="dimmed">
          Click a gap between two words to add a cut. Click a cut to move or remove it.
        </Text>
      )}

      {failure && (
        <Alert color="red" title="The cut was not changed">
          {describeError(failure)}
        </Alert>
      )}

      <ScrollArea.Autosize mah={420} type="auto">
        <Stack gap="sm" pr="sm">
          {groupByParagraph(words).map((paragraph) => (
            <Text key={paragraph[0].index} component="p" m={0} lh={2}>
              {paragraph.map((word) => {
                const k = word.index;
                const scene = sceneStarts.get(k);
                const cutScene = cuts.get(k);
                const tint = sceneOfWord[k] % 2 === 0 ? classes.tintA : classes.tintB;

                // A gap the picked-up cut can move to (it is not itself a cut).
                const isTarget =
                  selected !== null &&
                  cutScene === undefined &&
                  range !== null &&
                  k >= range.from &&
                  k <= range.to;
                let disabled = busy;
                if (selected !== null) {
                  disabled = disabled || (cutScene !== undefined ? k !== selected : !isTarget);
                }

                let label = `Add a cut after ${quoted(word)}`;
                if (cutScene !== undefined) {
                  label =
                    k === selected
                      ? `The ${CUT_SOURCE[cutScene.cut_source].label} cut after ${quoted(word)} is picked up. Click to put it down.`
                      : `${CUT_SOURCE[cutScene.cut_source].label} cut after ${quoted(word)}. Click to move or remove it.`;
                } else if (selected !== null) {
                  label = isTarget
                    ? `Move the cut here, after ${quoted(word)}`
                    : `A cut cannot move here`;
                }

                const gapClasses = [classes.gap];
                if (cutScene !== undefined) {
                  gapClasses.push(classes.cut, CUT_SOURCE[cutScene.cut_source].barClass);
                } else {
                  gapClasses.push(tint);
                }
                if (k === selected) {
                  gapClasses.push(classes.selected);
                } else if (isTarget) {
                  gapClasses.push(classes.target);
                }

                return (
                  <Fragment key={k}>
                    {scene && (
                      <Badge
                        size="xs"
                        variant="light"
                        color={
                          isOutsideLimits(
                            scene.end_s - scene.start_s,
                            project.min_scene_seconds,
                            project.max_scene_seconds,
                          )
                            ? "red"
                            : "gray"
                        }
                        mr={4}
                        style={{ verticalAlign: "middle" }}
                      >
                        {scene.index + 1} · {seconds(scene.end_s - scene.start_s)} s
                      </Badge>
                    )}
                    <span className={`${classes.word} ${tint}`}>{word.word}</span>
                    {k < words.length - 1 && (
                      <button
                        type="button"
                        className={gapClasses.join(" ")}
                        aria-label={label}
                        title={label}
                        disabled={disabled}
                        onClick={() => clickGap(k)}
                      />
                    )}
                  </Fragment>
                );
              })}
            </Text>
          ))}
        </Stack>
      </ScrollArea.Autosize>

      <Text size="xs" c="dimmed">
        Cuts placed by: <span className={`${classes.swatch} ${classes.cutAi}`} />
        the language model, <span className={`${classes.swatch} ${classes.cutRule}`} />
        the rule-based splitter, <span className={`${classes.swatch} ${classes.cutManual}`} />
        you. A red label marks a scene outside the project&apos;s limits ({project.min_scene_seconds}{" "}
        to {project.max_scene_seconds} s).
      </Text>

      <Modal
        opened={confirmation !== null}
        onClose={closeConfirmation}
        title="This edit clears scene inputs"
        centered
      >
        <Stack gap="sm">
          <Alert color="yellow" title="Scene inputs will be cleared">
            <Text size="sm">{confirmation?.message}</Text>
          </Alert>
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={closeConfirmation} disabled={busy}>
              Cancel
            </Button>
            <Button
              loading={busy}
              onClick={() => confirmation && send({ ...confirmation.edit, discard_inputs: true })}
            >
              Clear the inputs and edit
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
