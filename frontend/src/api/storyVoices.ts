import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { CHARACTER_LAB_KEY } from "./characterLab";
import { characterDefinitionsKey } from "./characterDefinitions";
import { characterImagesKey } from "./characterImages";
import { characterLinksKey } from "./characterLinks";
import { ApiError, detailMessage } from "./errors";
import { invalidateAfterJobAction } from "./jobs";
import { ACTIVE_POLL_MS } from "./polling";
import { PROJECTS_KEY, isValidProjectId } from "./projects";
import type { components } from "./schema";
import { VOICE_LAB_KEY, VOICES_KEY } from "./voiceLab";

export type CharacterVoices = components["schemas"]["StoryVoicesOut"];
export type VoiceEntry = components["schemas"]["StoryVoiceEntryOut"];
export type VoiceRunAll = components["schemas"]["StoryVoiceRunAllOut"];
export type NarratorVoice = components["schemas"]["NarratorVoiceOut"];

/** Every character-voices query of a project starts with this key (and the project's own). */
export function characterVoicesKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "character-voices"] as const;
}

export function narratorVoiceKey(projectId: number) {
  return [...PROJECTS_KEY, projectId, "narrator-voice"] as const;
}

/** What a finished voice changes: the character's voice, the pin, and the saved voices. */
function refreshAfterVoices(queryClient: QueryClient, projectId: number) {
  void queryClient.invalidateQueries({ queryKey: characterLinksKey(projectId) });
  void queryClient.invalidateQueries({ queryKey: characterDefinitionsKey(projectId) });
  void queryClient.invalidateQueries({ queryKey: characterImagesKey(projectId) });
  void queryClient.invalidateQueries({ queryKey: CHARACTER_LAB_KEY });
  void queryClient.invalidateQueries({ queryKey: VOICES_KEY });
  void queryClient.invalidateQueries({ queryKey: VOICE_LAB_KEY });
}

async function fetchVoices(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/character-voices",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the character voices (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/**
 * The newest list of characters with where each one's voice stands. It is loaded again every
 * few seconds while any voice is being made. When the last one finishes, a voice has been saved,
 * the character's version has gone up and the project's pin has moved, so the character links,
 * the definitions, the images, the Character lab and the saved voices are loaded again too.
 */
export function useCharacterVoices(projectId: number) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: characterVoicesKey(projectId),
    queryFn: () => fetchVoices(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.entries.some((entry) => entry.status === "in_progress")
        ? ACTIVE_POLL_MS
        : false,
  });

  const anyActive = query.data?.entries.some((entry) => entry.status === "in_progress") ?? false;
  const wasActive = useRef(false);
  useEffect(() => {
    if (wasActive.current && !anyActive) {
      refreshAfterVoices(queryClient, projectId);
    }
    wasActive.current = anyActive;
  }, [anyActive, projectId, queryClient]);

  return query;
}

async function fetchNarrator(projectId: number) {
  const { data, error, response } = await api.GET(
    "/api/projects/{project_id}/narrator-voice",
    { params: { path: { project_id: projectId } } },
  );
  if (!data) {
    throw new ApiError(
      detailMessage(error, `Could not load the narrator voice (HTTP ${response.status}).`),
      response.status,
    );
  }
  return data;
}

/** The narrator's newest voice and its status, loaded again while one is being made. */
export function useNarratorVoice(projectId: number) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: narratorVoiceKey(projectId),
    queryFn: () => fetchNarrator(projectId),
    enabled: isValidProjectId(projectId),
    refetchInterval: (current) =>
      current.state.data?.status === "in_progress" ? ACTIVE_POLL_MS : false,
  });

  const active = query.data?.status === "in_progress";
  const wasActive = useRef(false);
  useEffect(() => {
    if (wasActive.current && !active) {
      void queryClient.invalidateQueries({ queryKey: VOICES_KEY });
      void queryClient.invalidateQueries({ queryKey: VOICE_LAB_KEY });
    }
    wasActive.current = active;
  }, [active, queryClient]);

  return query;
}

/** A refusal can mean the definition or the Story Bible changed, so those are loaded again. */
function refreshAfterRun(queryClient: QueryClient, projectId: number) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: characterVoicesKey(projectId) }),
    queryClient.invalidateQueries({ queryKey: narratorVoiceKey(projectId) }),
    queryClient.invalidateQueries({ queryKey: characterDefinitionsKey(projectId) }),
    invalidateAfterJobAction(queryClient),
  ]);
}

/** "Make voices for all": starts a voice for every character (and the narrator) that needs one. */
export function useMakeAllVoices(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/character-voices/run",
        { params: { path: { project_id: projectId } } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the voices (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/**
 * Starts the voice of one character (a fresh one, also after a failure). `confirmOverwrite` is
 * true only after the user agreed to replace the voice of a character they chose from the
 * library.
 */
export function useMakeOneVoice(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { discoveryId: string; confirmOverwrite: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/character-voices/{discovery_id}/run",
        {
          params: { path: { project_id: projectId, discovery_id: input.discoveryId } },
          body: { confirm_overwrite: input.confirmOverwrite },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the voice (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/**
 * Derives the narrator's voice from the Story Bible. `confirmReplaceManual` is true only after
 * the user agreed to replace a voice they chose by hand.
 */
export function useDeriveNarratorVoice(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { confirmReplaceManual: boolean }) => {
      const { data, error, response } = await api.POST(
        "/api/projects/{project_id}/narrator-voice/run",
        {
          params: { path: { project_id: projectId } },
          body: { confirm_replace_manual: input.confirmReplaceManual },
        },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not start the narrator voice (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () => refreshAfterRun(queryClient, projectId),
  });
}

/** Makes a saved voice the narrator's. */
export function useChooseNarratorVoice(projectId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (voiceId: number) => {
      const { data, error, response } = await api.PUT(
        "/api/projects/{project_id}/narrator-voice",
        { params: { path: { project_id: projectId } }, body: { voice_id: voiceId } },
      );
      if (!data) {
        throw new ApiError(
          detailMessage(error, `Could not set the narrator voice (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: narratorVoiceKey(projectId) }),
  });
}
