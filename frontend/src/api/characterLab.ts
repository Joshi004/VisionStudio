import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import { LAB_KEY } from "./imageLab";
import { invalidateAfterJobAction, type JobSummary } from "./jobs";
import { ACTIVE_POLL_MS, isJobActive } from "./polling";
import type { components } from "./schema";
import { VIDEO_LAB_KEY } from "./videoLab";
import { VOICE_LAB_KEY, VOICES_KEY } from "./voiceLab";

export type LibraryCharacter = components["schemas"]["CharacterOut"];
export type CharacterIn = components["schemas"]["CharacterIn"];
export type CharacterPatch = components["schemas"]["CharacterPatch"];
export type CharacterOptions = components["schemas"]["OptionsOut"];
export type CharacterVersion = components["schemas"]["CharacterVersionOut"];
export type CharacterLook = components["schemas"]["LookOut"];
export type NamedLook = components["schemas"]["NamedLookOut"];
export type LookCandidate = components["schemas"]["LookCandidateOut"];
export type CharacterReference = components["schemas"]["CharacterReferenceOut"];
export type Angle = CharacterReference["angle"];
export type VoiceChoice = components["schemas"]["VoiceChoiceIn"];
export type AuditionSample = components["schemas"]["AuditionSampleOut"];
export type CharacterTake = components["schemas"]["TakeOut"];
export type TakeCreate = components["schemas"]["TakeIn"];
export type TakeRerun = components["schemas"]["RerunIn"];
export type TakeStep = NonNullable<CharacterTake["active_step"]>;
/** How a MiniMax H3 clip uses the speech: MiniMax's own words for it. */
export type AudioMarker = TakeCreate["audio_marker"];

const PAGE_SIZE = 20;

/** Every Character lab query starts with this key. */
export const CHARACTER_LAB_KEY = ["lab", "characters"] as const;
const listKey = [...CHARACTER_LAB_KEY, "list"] as const;
const optionsKey = [...CHARACTER_LAB_KEY, "options"] as const;
const detailKey = (characterId: number | null) =>
  [...CHARACTER_LAB_KEY, "detail", characterId] as const;
const looksKey = (characterId: number | null) =>
  [...CHARACTER_LAB_KEY, "looks", characterId] as const;
const takesKey = (characterId: number | null) =>
  [...CHARACTER_LAB_KEY, "takes", characterId] as const;
const versionsKey = (characterId: number | null) =>
  [...CHARACTER_LAB_KEY, "versions", characterId] as const;
const namedLooksKey = (characterId: number | null) =>
  [...CHARACTER_LAB_KEY, "named-looks", characterId] as const;

function failure(error: unknown, status: number, what: string): ApiError {
  return new ApiError(detailMessage(error, `${what} (HTTP ${status}).`), status);
}

// --- What a look or a take is doing now -------------------------------------------------------

/**
 * Is a look still being made? It waits for the picture it is drawn from (a look the story
 * pipeline makes for a younger or older self), its prompt is being written, a candidate is
 * being drawn, or its angles are. The API names no job for an angle, so a look that is `making_angles` counts as
 * busy until it turns `ready`.
 */
export function lookIsBusy(look: CharacterLook): boolean {
  if (
    look.status === "waiting" ||
    look.status === "writing_prompt" ||
    look.status === "making_angles"
  ) {
    return true;
  }
  return look.status === "choosing" && look.candidates.some((candidate) => isJobActive(candidate.job));
}

/** The first step of a take whose job failed or was cancelled, or null. */
export function failedStepJob(take: CharacterTake): JobSummary | null {
  const jobs = [
    take.prompt_job,
    take.image?.job,
    take.last_frame?.job,
    take.voice?.job,
    take.video?.job,
  ];
  for (const job of jobs) {
    if (job && (job.status === "failed" || job.status === "cancelled")) {
      return job;
    }
  }
  return null;
}

/**
 * Where a take is:
 * - `done`: nothing is left to make.
 * - `running`: a step is waiting or running.
 * - `failed`: a step's job failed, or the next step could not start (`last_error`).
 * - `waiting`: nothing runs and nothing failed. A take made with "Create" is between two steps
 *   (the next one starts by itself within a moment), or it lost its place when the backend
 *   restarted and "Continue" starts it again.
 */
export type TakeStatus = "done" | "running" | "failed" | "waiting";

export function takeStatus(take: CharacterTake): TakeStatus {
  if (take.next_step === null) {
    return "done";
  }
  if (take.active_step !== null) {
    return "running";
  }
  if (take.last_error !== null || failedStepJob(take) !== null) {
    return "failed";
  }
  return "waiting";
}

// --- Refreshing --------------------------------------------------------------------------------

/**
 * Anything done here can change the Character lab, the Image, Voice and Video labs (a look's
 * pictures, an audition's samples and a take's picture, speech and clip are ordinary lab runs),
 * the saved voices, and the jobs. Only the queries on screen are fetched again; the others are
 * marked old.
 */
function refreshAfterChange(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: CHARACTER_LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: VOICE_LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: VIDEO_LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: VOICES_KEY }),
    invalidateAfterJobAction(queryClient),
  ]);
}

// --- The library -------------------------------------------------------------------------------

async function fetchCharacters(includeArchived: boolean, beforeId: number | undefined) {
  const { data, error, response } = await api.GET("/api/lab/characters", {
    params: {
      query: { include_archived: includeArchived, before_id: beforeId, limit: PAGE_SIZE },
    },
  });
  if (!data) {
    throw failure(error, response.status, "Could not load the characters");
  }
  return data;
}

/** The characters, newest first, a page at a time. Archived ones only when asked for. */
export function useLibraryCharacters(includeArchived: boolean) {
  return useInfiniteQuery({
    queryKey: [...listKey, includeArchived],
    queryFn: ({ pageParam }) => fetchCharacters(includeArchived, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_before_id ?? undefined,
  });
}

async function fetchOptions() {
  const { data, response } = await api.GET("/api/lab/characters/options");
  if (!data) {
    throw new ApiError(`Could not load the suggestions (HTTP ${response.status}).`, response.status);
  }
  return data;
}

/** The gender and species suggestions: a few fixed ones, and every value already used. */
export function useCharacterOptions() {
  return useQuery({ queryKey: optionsKey, queryFn: fetchOptions });
}

async function fetchCharacter(characterId: number) {
  const { data, error, response } = await api.GET("/api/lab/characters/{character_id}", {
    params: { path: { character_id: characterId } },
  });
  if (!data) {
    throw failure(error, response.status, "Could not load the character");
  }
  return data;
}

/** One character with its current look. Nothing is loaded while `characterId` is null. */
export function useLibraryCharacter(characterId: number | null) {
  return useQuery({
    queryKey: detailKey(characterId),
    queryFn: () => fetchCharacter(characterId as number),
    enabled: characterId !== null,
  });
}

export function useCreateCharacter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: CharacterIn) => {
      const { data, error, response } = await api.POST("/api/lab/characters", { body });
      if (!data) {
        throw failure(error, response.status, "The character was not saved");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/** Changes the profile, archives or unarchives a character, or both at once. */
export function useEditCharacter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { characterId: number; body: CharacterPatch }) => {
      const { data, error, response } = await api.PATCH("/api/lab/characters/{character_id}", {
        params: { path: { character_id: input.characterId } },
        body: input.body,
      });
      if (!data) {
        throw failure(error, response.status, "The character was not saved");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

// --- Looks -------------------------------------------------------------------------------------

async function fetchLooks(characterId: number) {
  const { data, error, response } = await api.GET("/api/lab/characters/{character_id}/looks", {
    params: { path: { character_id: characterId } },
  });
  if (!data) {
    throw failure(error, response.status, "Could not load the looks");
  }
  return data;
}

/**
 * Every look of a character, newest first. They are loaded again every few seconds while one
 * is being made. When a look turns ready it becomes the character's current look and adds a
 * version, so the character, the library and the versions are loaded again then.
 */
export function useCharacterLooks(characterId: number | null) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: looksKey(characterId),
    enabled: characterId !== null,
    refetchInterval: (query) => (query.state.data?.some(lookIsBusy) ? ACTIVE_POLL_MS : false),
    queryFn: async () => {
      const before = queryClient.getQueryData<CharacterLook[]>(looksKey(characterId));
      const looks = await fetchLooks(characterId as number);
      const turnedReady = looks.some(
        (look) =>
          look.status === "ready" &&
          before?.some((old) => old.id === look.id && old.status !== "ready"),
      );
      if (turnedReady) {
        void queryClient.invalidateQueries({ queryKey: detailKey(characterId) });
        void queryClient.invalidateQueries({ queryKey: listKey });
        void queryClient.invalidateQueries({ queryKey: versionsKey(characterId) });
      }
      return looks;
    },
  });
}

/** Starts a new look: the prompt is written, then four candidates are drawn to choose from. */
export function useStartLook() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (characterId: number) => {
      const { data, error, response } = await api.POST("/api/lab/characters/{character_id}/looks", {
        params: { path: { character_id: characterId } },
      });
      if (!data) {
        throw failure(error, response.status, "The look was not started");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/**
 * Starts a new look from the author's own picture (a lab image, uploaded first): the prompt is
 * written for that picture, then four candidates are made by editing it.
 */
export function useStartLookFromPicture() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { characterId: number; imageId: number }) => {
      const { data, error, response } = await api.POST(
        "/api/lab/characters/{character_id}/looks/from-picture",
        {
          params: { path: { character_id: input.characterId } },
          body: { image_id: input.imageId },
        },
      );
      if (!data) {
        throw failure(error, response.status, "The look was not started");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/** Chooses one candidate as the master. The other four angles are then made by themselves. */
export function useChooseMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { lookId: number; candidateId: number }) => {
      const { data, error, response } = await api.POST("/api/lab/characters/looks/{look_id}/master", {
        params: { path: { look_id: input.lookId } },
        body: { candidate_id: input.candidateId },
      });
      if (!data) {
        throw failure(error, response.status, "The master was not chosen");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/** Makes one more picture for a single angle. */
export function useRedoAngle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { lookId: number; angle: Angle }) => {
      const { data, error, response } = await api.POST(
        "/api/lab/characters/looks/{look_id}/angles/{angle}",
        { params: { path: { look_id: input.lookId, angle: input.angle } } },
      );
      if (!data) {
        throw failure(error, response.status, "The angle was not started");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/** Makes an earlier ready look the character's current look. This adds a version. */
export function useSetCurrentLook() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { characterId: number; lookId: number }) => {
      const { data, error, response } = await api.PUT(
        "/api/lab/characters/{character_id}/current-look",
        {
          params: { path: { character_id: input.characterId } },
          body: { look_id: input.lookId },
        },
      );
      if (!data) {
        throw failure(error, response.status, "The look was not changed");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

// --- Versions ----------------------------------------------------------------------------------

async function fetchVersions(characterId: number) {
  const { data, error, response } = await api.GET("/api/lab/characters/{character_id}/versions", {
    params: { path: { character_id: characterId } },
  });
  if (!data) {
    throw failure(error, response.status, "Could not load the versions");
  }
  return data;
}

/**
 * Every version of a character, newest first. A version is never edited, so nothing here is
 * followed while it is open: it is loaded again after any change made in the lab.
 */
export function useCharacterVersions(characterId: number | null) {
  return useQuery({
    queryKey: versionsKey(characterId),
    queryFn: () => fetchVersions(characterId as number),
    enabled: characterId !== null,
  });
}

// --- Named looks -------------------------------------------------------------------------------

async function fetchNamedLooks(characterId: number) {
  const { data, error, response } = await api.GET(
    "/api/lab/characters/{character_id}/named-looks",
    { params: { path: { character_id: characterId } } },
  );
  if (!data) {
    throw failure(error, response.status, "Could not load the named looks");
  }
  return data;
}

/**
 * The named looks of a character (such as night clothes), read-only. A story project's
 * resolution creates them and makes their pictures, so they are loaded again after any change.
 */
export function useNamedLooks(characterId: number | null) {
  return useQuery({
    queryKey: namedLooksKey(characterId),
    queryFn: () => fetchNamedLooks(characterId as number),
    enabled: characterId !== null,
  });
}

// --- Voice -------------------------------------------------------------------------------------

/** Saves what the audition's samples are made from. An empty text clears it. */
export function useSetVoiceDescription() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { characterId: number; voiceDescription: string | null }) => {
      const { data, error, response } = await api.PUT(
        "/api/lab/characters/{character_id}/voice/description",
        {
          params: { path: { character_id: input.characterId } },
          body: { voice_description: input.voiceDescription },
        },
      );
      if (!data) {
        throw failure(error, response.status, "The voice description was not saved");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/**
 * Starts the job that writes a short line to read while auditioning (a paid call to the
 * language model). It answers with that job: follow it with `useJob`, and read
 * `output.audition_line` when it has succeeded.
 */
export function useStartAuditionLine() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (characterId: number) => {
      const { data, error, response } = await api.POST(
        "/api/lab/characters/{character_id}/voice/audition-line",
        { params: { path: { character_id: characterId } } },
      );
      if (!data) {
        throw failure(error, response.status, "The line was not started");
      }
      return data;
    },
    onSuccess: () => invalidateAfterJobAction(queryClient),
  });
}

/**
 * Starts three samples of one line, read in the voice description. Each is a paid GPU job of
 * one to three minutes. The samples are not kept on the character: follow each with
 * `useVoiceLabRun(sample.voice_run_id)`.
 */
export function useStartAuditions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { characterId: number; line: string }) => {
      const { data, error, response } = await api.POST(
        "/api/lab/characters/{character_id}/voice/auditions",
        {
          params: { path: { character_id: input.characterId } },
          body: { line: input.line },
        },
      );
      if (!data) {
        throw failure(error, response.status, "The auditions were not started");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/** Sets the voice: an existing saved voice, an audition sample (saved by name), or none. */
export function useSetVoice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { characterId: number; choice: VoiceChoice }) => {
      const { data, error, response } = await api.PUT("/api/lab/characters/{character_id}/voice", {
        params: { path: { character_id: input.characterId } },
        body: input.choice,
      });
      if (!data) {
        throw failure(error, response.status, "The voice was not saved");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

// --- Takes -------------------------------------------------------------------------------------

async function fetchTakes(characterId: number, beforeId: number | undefined) {
  const { data, error, response } = await api.GET("/api/lab/characters/{character_id}/takes", {
    params: {
      path: { character_id: characterId },
      query: { before_id: beforeId, limit: PAGE_SIZE },
    },
  });
  if (!data) {
    throw failure(error, response.status, "Could not load the gallery");
  }
  return data;
}

/**
 * The character's gallery, newest first, a page at a time. It is loaded again every few
 * seconds while a take is running, and while one waits between two steps, so a picture, a
 * speech and a clip appear by themselves when they are done.
 */
export function useCharacterTakes(characterId: number | null) {
  return useInfiniteQuery({
    queryKey: takesKey(characterId),
    queryFn: ({ pageParam }) => fetchTakes(characterId as number, pageParam),
    enabled: characterId !== null,
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_before_id ?? undefined,
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) =>
        page.takes.some((take) => {
          const status = takeStatus(take);
          return status === "running" || status === "waiting";
        }),
      )
        ? ACTIVE_POLL_MS
        : false,
  });
}

/**
 * Saves a take and starts its first step, and returns at once. Each step is a paid call: the
 * prompts a call to the language model, a picture and a speech GPU jobs of a few minutes, a
 * clip one of 5 to 10 minutes or more.
 */
export function useCreateTake() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { characterId: number; body: TakeCreate }) => {
      const { data, error, response } = await api.POST("/api/lab/characters/{character_id}/takes", {
        params: { path: { character_id: input.characterId } },
        body: input.body,
      });
      if (!data) {
        throw failure(error, response.status, "The take was not started");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/** Starts the next step of a take. When a step failed, this tries that step again. */
export function useContinueTake() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (takeId: number) => {
      const { data, error, response } = await api.POST(
        "/api/lab/characters/takes/{take_id}/continue",
        { params: { path: { take_id: takeId } } },
      );
      if (!data) {
        throw failure(error, response.status, "The step was not started");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/** Sends edited prompts and starts what that frees. Only the prompts that changed are sent. */
export function useRerunTake() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { takeId: number; body: TakeRerun }) => {
      const { data, error, response } = await api.POST("/api/lab/characters/takes/{take_id}/rerun", {
        params: { path: { take_id: input.takeId } },
        body: input.body,
      });
      if (!data) {
        throw failure(error, response.status, "The take was not run again");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}
