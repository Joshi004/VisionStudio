import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import type { components } from "./schema";

export type Character = components["schemas"]["CharacterOut"];
export type CharacterCreate = components["schemas"]["CharacterCreate"];
export type CharacterUpdate = components["schemas"]["CharacterUpdate"];

/** Every query of the cast starts with this key. */
export const CHARACTERS_KEY = ["lab", "characters"] as const;

async function fetchCharacters() {
  const { data, response } = await api.GET("/api/lab/characters");
  if (!data) {
    throw new ApiError(`Could not load the cast (HTTP ${response.status}).`, response.status);
  }
  return data;
}

/** The cast of the Talking character lab, newest first. */
export function useCharacters() {
  return useQuery({ queryKey: CHARACTERS_KEY, queryFn: fetchCharacters });
}

/** Saves a character: a name, a picture, a description and an optional default voice. */
export function useCreateCharacter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: CharacterCreate) => {
      const { data, error, response } = await api.POST("/api/lab/characters", { body });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The character was not saved (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHARACTERS_KEY }),
  });
}

/** Changes the fields of a character that are sent. */
export function useUpdateCharacter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { characterId: number; body: CharacterUpdate }) => {
      const { data, error, response } = await api.PATCH("/api/lab/characters/{character_id}", {
        params: { path: { character_id: input.characterId } },
        body: input.body,
      });
      if (!data) {
        throw new ApiError(
          detailMessage(error, `The character was not saved (HTTP ${response.status}).`),
          response.status,
        );
      }
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CHARACTERS_KEY }),
  });
}
