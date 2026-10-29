import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { CHARACTER_LAB_KEY } from "./characterLab";
import { ApiError, detailMessage } from "./errors";
import { LAB_KEY } from "./imageLab";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS } from "./polling";
import type { components } from "./schema";
import { VIDEO_LAB_KEY } from "./videoLab";
import { VOICE_LAB_KEY } from "./voiceLab";

export type AvTest = components["schemas"]["TestOut"];
export type AvTestCreate = components["schemas"]["TestIn"];
export type AvSegment = components["schemas"]["SegmentOut"];
export type AvStatus = AvTest["status"];
export type AvMarker = AvTestCreate["audio_marker"];

const PAGE_SIZE = 10;

const avTestsKey = (characterId: number | null) =>
  [...CHARACTER_LAB_KEY, "av-tests", characterId] as const;

function failure(error: unknown, status: number, what: string): ApiError {
  return new ApiError(detailMessage(error, `${what} (HTTP ${status}).`), status);
}

/**
 * Is the test still being made? The speech, the word times, the clips and the render each move it
 * along by themselves, so the page asks again until it is `ready`, `done` or `failed`.
 */
export function avTestIsMoving(test: AvTest): boolean {
  return (
    test.status === "speaking" ||
    test.status === "timing" ||
    test.status === "clips" ||
    test.status === "rendering"
  );
}

/**
 * A test's speech, its parts' clips and its renders are ordinary Voice lab, Video lab and
 * Character lab rows and jobs, so all of them are fetched again after any change here.
 */
function refreshAfterChange(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: CHARACTER_LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: VOICE_LAB_KEY }),
    queryClient.invalidateQueries({ queryKey: VIDEO_LAB_KEY }),
    invalidateAfterJobAction(queryClient),
  ]);
}

async function fetchAvTests(characterId: number, beforeId: number | undefined) {
  const { data, error, response } = await api.GET("/api/lab/characters/{character_id}/av-tests", {
    params: {
      path: { character_id: characterId },
      query: { before_id: beforeId, limit: PAGE_SIZE },
    },
  });
  if (!data) {
    throw failure(error, response.status, "Could not load the tests");
  }
  return data;
}

/** The character's Audio video tests, newest first, a page at a time. */
export function useAvTests(characterId: number | null) {
  return useInfiniteQuery({
    queryKey: avTestsKey(characterId),
    queryFn: ({ pageParam }) => fetchAvTests(characterId as number, pageParam),
    enabled: characterId !== null,
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_before_id ?? undefined,
    refetchInterval: (query) =>
      query.state.data?.pages.some((page) => page.tests.some(avTestIsMoving))
        ? ACTIVE_POLL_MS
        : false,
  });
}

/**
 * Starts a test: one speech of the whole text (a paid GPU job), then, by itself, the timing of
 * its words and one paid video clip for each marked part. It returns at once.
 */
export function useCreateAvTest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { characterId: number; body: AvTestCreate }) => {
      const { data, error, response } = await api.POST(
        "/api/lab/characters/{character_id}/av-tests",
        {
          params: { path: { character_id: input.characterId } },
          body: input.body,
        },
      );
      if (!data) {
        throw failure(error, response.status, "The test was not started");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/** Makes the two videos of a test whose clips are ready. FFmpeg only: nothing is paid for. */
export function useRenderAvTest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (testId: number) => {
      const { data, error, response } = await api.POST(
        "/api/lab/characters/av-tests/{test_id}/render",
        { params: { path: { test_id: testId } } },
      );
      if (!data) {
        throw failure(error, response.status, "The videos were not started");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}

/**
 * Makes a new test from an earlier one with another way of using the speech. The speech, its
 * word times and the first frame are kept; each clip is made again (a paid video run each).
 */
export function useCopyAvTest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { testId: number; audioMarker: AvMarker }) => {
      const { data, error, response } = await api.POST(
        "/api/lab/characters/av-tests/{test_id}/copy",
        {
          params: { path: { test_id: input.testId } },
          body: { audio_marker: input.audioMarker },
        },
      );
      if (!data) {
        throw failure(error, response.status, "The test was not copied");
      }
      return data;
    },
    onSuccess: () => refreshAfterChange(queryClient),
  });
}
