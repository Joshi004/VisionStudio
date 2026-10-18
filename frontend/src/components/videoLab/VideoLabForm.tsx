import type { Dispatch, SetStateAction } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Group,
  NumberInput,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";

import { H3_MODEL, LAB_VIDEO_MODELS, videoModelLabel, type LabVideoModel } from "../../videoModels";
import { FirstFramePicker } from "./FirstFramePicker";
import { labPromptHints } from "./labPromptHints";
import { PromptHelper } from "./PromptHelper";
import { ReferenceComposer } from "./ReferenceComposer";
import {
  costText,
  DEFAULT_FORM,
  durationLimits,
  durationOf,
  formProblem,
  H3_STEPS_MAX,
  H3_STEPS_MIN,
  matchesAudio,
  referenceCostText,
  referencePictures,
  referenceSkeleton,
  referenceVoices,
  shapeLabel,
  usesH3,
  type LabKind,
  type VideoLabFormState,
} from "./videoLabView";

type VideoLabFormProps = {
  state: VideoLabFormState;
  /** Takes a function of the current form as well, so a change made while an upload runs (a
   * first frame, a reference picture) does not undo what was typed meanwhile. */
  onChange: Dispatch<SetStateAction<VideoLabFormState>>;
  onRun: () => void;
  running: boolean;
};

function runLabel(state: VideoLabFormState): string {
  if (state.kind === "h3_reference") {
    return "Run the MiniMax H3 reference clip";
  }
  const models: LabVideoModel[] = state.models;
  if (models.length === 1) {
    return `Run on ${videoModelLabel(models[0])}`;
  }
  return models.length === 0 ? "Run" : `Run on ${models.length} models`;
}

/**
 * The Video lab's form: the prompt, the model or models, the recipe, the shape and length of
 * the clip, the seed and an optional first frame and last frame. Several models make several runs
 * that differ only by the model: the same prompt, first frame, length, recipe and seed (MiniMax
 * H3 also has its own size, frame rate and steps). The other mode makes one MiniMax H3 clip from
 * up to 9 pictures (one or two characters, a scene, other pictures) and optional voices.
 */
export function VideoLabForm({ state, onChange, onRun, running }: VideoLabFormProps) {
  const problem = formProblem(state);
  const duration = durationOf(state);
  const isReference = state.kind === "h3_reference";
  const hints = labPromptHints({
    prompt: state.prompt,
    durationS: duration,
    models: isReference ? [H3_MODEL] : state.models,
    kind: state.kind,
    pictureCount: referencePictures(state).length,
    audioCount: referenceVoices(state).length,
  });
  const has23 = state.models.includes("ltx-2.3");
  const hasH3 = usesH3(state);
  const hasLtx = !isReference && state.models.some((model) => model !== H3_MODEL);
  const limits = durationLimits();
  const lengthLocked = isReference && matchesAudio(state);
  const hasVoice = referenceVoices(state).length > 0;

  function update(changes: Partial<VideoLabFormState>) {
    onChange((current) => ({ ...current, ...changes }));
  }

  function changeKind(kind: LabKind) {
    onChange((current) => {
      if (current.kind === kind) {
        return current;
      }
      // Reference mode needs the six-part prompt: offer its skeleton when nothing is written.
      const offerSkeleton = kind === "h3_reference" && current.prompt.trim() === "";
      const prompt = offerSkeleton ? referenceSkeleton(current) : current.prompt;
      return {
        ...current,
        kind,
        prompt,
        skeletonText: offerSkeleton ? prompt : current.skeletonText,
        // The reference clip is always MiniMax H3; going back restores the default choice.
        models: kind === "h3_reference" ? [H3_MODEL] : DEFAULT_FORM.models,
      };
    });
  }

  // The skeleton can be made again only while the prompt is empty or is still exactly the
  // skeleton the form put in, so nothing typed is ever overwritten.
  const skeletonSafe = state.prompt.trim() === "" || state.prompt === state.skeletonText;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (problem === null) {
          onRun();
        }
      }}
    >
      <Stack gap="md">
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            What to make
          </Text>
          <SegmentedControl
            value={state.kind}
            onChange={(value) => changeKind(value === "h3_reference" ? "h3_reference" : "generate")}
            data={[
              { value: "generate", label: "Generate (text, first or last frame)" },
              { value: "h3_reference", label: "MiniMax H3 reference (characters, scene, voices)" },
            ]}
          />
        </Stack>

        {isReference ? (
          <Text size="sm" c="dimmed">
            Model: <b>MiniMax H3</b>. The pictures show who and what is in the clip. A voice is
            optional: H3 follows its timbre and delivery, and the words spoken come from the
            prompt. It makes its own sound, so the recording is not in the clip.
          </Text>
        ) : (
          <Checkbox.Group
            label="Models"
            description="Choose several to compare them: the clips differ only by the model."
            value={state.models}
            onChange={(value) =>
              update({
                models: LAB_VIDEO_MODELS.map((entry) => entry.value).filter((model) =>
                  value.includes(model),
                ),
              })
            }
          >
            <Group gap="lg" mt={6}>
              {LAB_VIDEO_MODELS.map((entry) => (
                <Checkbox key={entry.value} value={entry.value} label={entry.label} />
              ))}
            </Group>
          </Checkbox.Group>
        )}

        <Group align="flex-start" gap="md">
          {!isReference && (
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                Recipe
              </Text>
              <SegmentedControl
                value={state.mode}
                onChange={(value) => update({ mode: value === "fast" ? "fast" : "quality" })}
                disabled={!hasLtx}
                data={[
                  { value: "quality", label: "Quality" },
                  { value: "fast", label: "Fast" },
                ]}
              />
              <Text size="xs" c="dimmed" maw={260}>
                LTX only. Quality is sharper and slower. LTX-2.5 quality is the DFR recipe.
                MiniMax H3 has one recipe.
              </Text>
            </Stack>
          )}
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Shape
            </Text>
            <SegmentedControl
              value={state.orientation}
              onChange={(value) =>
                update({ orientation: value === "landscape" ? "landscape" : "portrait" })
              }
              data={[
                { value: "portrait", label: shapeLabel("portrait", state) },
                { value: "landscape", label: shapeLabel("landscape", state) },
              ]}
            />
          </Stack>
          <NumberInput
            label="Length (seconds)"
            description={
              lengthLocked
                ? "The length of the first voice."
                : `${limits.min} to ${limits.max}. 24 fps.`
            }
            value={state.durationS}
            onChange={(value) => update({ durationS: value })}
            min={limits.min}
            max={limits.max}
            step={1}
            decimalScale={1}
            allowNegative={false}
            clampBehavior="none"
            disabled={lengthLocked}
            w={170}
          />
          <TextInput
            label="Seed"
            description={isReference ? "Empty: random." : "Empty: random. All runs share it."}
            value={state.seed}
            onChange={(event) => update({ seed: event.currentTarget.value })}
            w={190}
          />
          {hasH3 && (
            <TextInput
              label="Steps (MiniMax H3 only)"
              description={`${H3_STEPS_MIN} to ${H3_STEPS_MAX}. Empty: 50. Fewer is faster and rougher.`}
              value={state.steps}
              onChange={(event) => update({ steps: event.currentTarget.value })}
              w={230}
            />
          )}
        </Group>

        {isReference ? (
          <>
            <ReferenceComposer state={state} onChange={onChange} />
            <Checkbox
              label="Make the clip as long as the first voice"
              description={
                hasVoice
                  ? "The GPU server decides the final length: see the measured length on the run. Untick it to choose the length above."
                  : "Needs a voice. Without one, the length above is used."
              }
              checked={state.matchAudio && hasVoice}
              disabled={!hasVoice}
              onChange={(event) => update({ matchAudio: event.currentTarget.checked })}
            />
          </>
        ) : (
          <>
            <FirstFramePicker
              value={state.firstFrame}
              // Without a first frame there can be no last frame.
              onChange={(firstFrame) =>
                onChange((current) =>
                  firstFrame === null
                    ? { ...current, firstFrame, lastFrame: null }
                    : { ...current, firstFrame },
                )
              }
            />

            <FirstFramePicker
              role="last"
              value={state.lastFrame}
              disabled={state.firstFrame === null}
              onChange={(lastFrame) => update({ lastFrame })}
            />
            {hasH3 && state.lastFrame !== null && (
              <Text size="xs" c="dimmed">
                MiniMax H3 reaches the last frame at the very end of the clip, so give it a clip
                long enough for the path between the two frames.
              </Text>
            )}

            <PromptHelper
              durationS={duration}
              hasFirstFrame={state.firstFrame !== null}
              models={state.models}
              onUse={(prompt) => update({ prompt })}
            />
          </>
        )}

        <Stack gap={4}>
          <Textarea
            label="Prompt"
            description={
              isReference
                ? "Six parts: subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, non_diegetic_music. Name each picture as <Picture n> and each voice as <Audio n>; spoken words go inside <d>[English] …</d>. Fill the blanks in [brackets]."
                : "One paragraph, present tense. For LTX-2.5 cuts, name each transition in a sentence. MiniMax H3 reads three fields instead; when a first or last frame is given, the app writes the first line that places it."
            }
            value={state.prompt}
            onChange={(event) => update({ prompt: event.currentTarget.value })}
            autosize
            minRows={5}
            maxLength={8000}
          />
          {isReference && (
            <Group>
              <Button
                size="compact-sm"
                variant="default"
                disabled={!skeletonSafe}
                onClick={() => {
                  const skeleton = referenceSkeleton(state);
                  update({ prompt: skeleton, skeletonText: skeleton });
                }}
              >
                Fill the prompt from the cast
              </Button>
              <Text size="xs" c="dimmed">
                {skeletonSafe
                  ? "Made from the characters, scene and ambience above. Press it again after changing them."
                  : "Clear the prompt first: the skeleton never replaces what you wrote."}
              </Text>
            </Group>
          )}
          {hints.map((hint) => (
            <Text key={hint} size="xs" c="orange.8">
              {hint}
            </Text>
          ))}
        </Stack>

        {!isReference && (
          <Textarea
            label="Negative prompt (LTX-2.3 only)"
            description="Empty: the GPU server's own default negative prompt. LTX-2.5 and MiniMax H3 have no negative prompt and are sent none."
            value={state.negativePrompt}
            onChange={(event) => update({ negativePrompt: event.currentTarget.value })}
            disabled={!has23}
            autosize
            minRows={2}
            maxLength={2000}
          />
        )}

        <Stack gap={6} align="flex-start">
          <Button type="submit" loading={running} disabled={problem !== null}>
            {runLabel(state)}
          </Button>
          {problem !== null && state.prompt.trim() !== "" && (
            <Alert color="yellow" p="xs">
              {problem}
            </Alert>
          )}
          {(isReference || state.models.length > 0) && (
            <Text size="xs" c="dimmed">
              {isReference ? referenceCostText() : costText(state.models)} A run starts only when
              you press the button.
            </Text>
          )}
        </Stack>
      </Stack>
    </form>
  );
}
