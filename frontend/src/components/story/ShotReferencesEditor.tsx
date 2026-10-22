import { useState } from "react";
import type { ReactNode } from "react";
import { Button, Group, Stack, Text } from "@mantine/core";

import type { ShotReferenceManifest } from "../../api/shotReferences";
import { H3_MAX_REFERENCES } from "../videoLab/videoLabView";
import { EditorActions } from "./editorParts";
import { PromptHoverCard } from "./PromptHoverCard";
import { pictureLabel } from "./referencePictureFormat";
import type { PictureLike } from "./referencePictureFormat";

type ShotReferencesEditorProps = {
  /** The shot's newest manifest: its pictures are the starting choice, its catalog the options. */
  manifest: ShotReferenceManifest;
  saving: boolean;
  error: unknown;
  /** The chosen pictures' Image Lab ids, in the order they will be sent. */
  onSave: (labImageIds: number[]) => void;
  onCancel: () => void;
};

/** What the editor needs of a picture, whether it was chosen or only in the catalog. */
type Picture = PictureLike & { lab_image_id: number; url: string | null };

type PictureCardProps = {
  picture: Picture;
  /** The buttons under the picture. */
  children: ReactNode;
};

/** One picture with its label and buttons. A character is shown at 2:3 and a place at 16:9. */
function PictureCard({ picture, children }: PictureCardProps) {
  const environment = picture.kind === "environment";
  return (
    <Stack gap={4} w={environment ? 160 : 90}>
      {picture.url !== null ? (
        <PromptHoverCard imageId={picture.lab_image_id} block>
          <img
            src={picture.url}
            alt={pictureLabel(picture)}
            loading="lazy"
            style={{
              width: "100%",
              aspectRatio: environment ? "16 / 9" : "2 / 3",
              objectFit: "cover",
              borderRadius: 4,
              display: "block",
              background: "var(--mantine-color-gray-1)",
            }}
          />
        </PromptHoverCard>
      ) : (
        <Text size="xs" c="red">
          The picture no longer exists.
        </Text>
      )}
      <Text size="xs" style={{ wordBreak: "break-word" }}>
        {pictureLabel(picture)}
      </Text>
      {children}
    </Stack>
  );
}

/**
 * The pictures one shot is generated from, chosen by hand: put pictures of the shot's catalog in
 * the order they should be sent, up to what the video model takes. Unlike the fixed rule, this
 * does not insist on every angle of a character or on the place. The server checks that each
 * picture is one the shot can use now.
 */
export function ShotReferencesEditor({
  manifest,
  saving,
  error,
  onSave,
  onCancel,
}: ShotReferencesEditorProps) {
  const [chosen, setChosen] = useState<number[]>(
    manifest.references.map((picture) => picture.lab_image_id),
  );

  // The chosen pictures are looked up first, so one that is no longer in the catalog still shows.
  const pictures = new Map<number, Picture>(
    [...manifest.catalog, ...manifest.references].map((picture) => [
      picture.lab_image_id,
      picture,
    ]),
  );
  const available = manifest.catalog.filter(
    (picture) => !chosen.includes(picture.lab_image_id),
  );
  const full = chosen.length >= H3_MAX_REFERENCES;

  const move = (index: number, offset: number) => {
    const target = index + offset;
    if (target < 0 || target >= chosen.length) {
      return;
    }
    const next = [...chosen];
    [next[index], next[target]] = [next[target], next[index]];
    setChosen(next);
  };

  return (
    <Stack gap="md">
      <Stack gap={6}>
        <Text size="sm" fw={500}>
          Chosen, in the order they are sent ({chosen.length} of{" "}
          {H3_MAX_REFERENCES})
        </Text>
        {chosen.length === 0 ? (
          <Text size="sm" c="dimmed">
            Nothing chosen. A shot needs at least one picture.
          </Text>
        ) : (
          <Group gap="md" align="flex-start">
            {chosen.map((id, index) => {
              const picture = pictures.get(id);
              return picture === undefined ? null : (
                <PictureCard key={id} picture={picture}>
                  <Text size="xs" c="dimmed">
                    {index + 1}
                  </Text>
                  <Group gap={4}>
                    <Button
                      size="compact-xs"
                      variant="default"
                      aria-label={`Move picture ${index + 1} earlier`}
                      disabled={index === 0}
                      onClick={() => move(index, -1)}
                    >
                      {"\u2190"}
                    </Button>
                    <Button
                      size="compact-xs"
                      variant="default"
                      aria-label={`Move picture ${index + 1} later`}
                      disabled={index === chosen.length - 1}
                      onClick={() => move(index, 1)}
                    >
                      {"\u2192"}
                    </Button>
                    <Button
                      size="compact-xs"
                      variant="default"
                      onClick={() =>
                        setChosen(chosen.filter((value) => value !== id))
                      }
                    >
                      Remove
                    </Button>
                  </Group>
                </PictureCard>
              );
            })}
          </Group>
        )}
      </Stack>

      <Stack gap={6}>
        <Text size="sm" fw={500}>
          Pictures this shot can use
        </Text>
        {available.length === 0 ? (
          <Text size="sm" c="dimmed">
            Every picture the shot can use is chosen.
          </Text>
        ) : (
          <Group gap="md" align="flex-start">
            {available.map((picture) => (
              <PictureCard key={picture.lab_image_id} picture={picture}>
                {!picture.is_resolved && (
                  <Text size="xs" c="dimmed">
                    default look
                  </Text>
                )}
                <Button
                  size="compact-xs"
                  variant="default"
                  disabled={full}
                  onClick={() => setChosen([...chosen, picture.lab_image_id])}
                >
                  Add
                </Button>
              </PictureCard>
            ))}
          </Group>
        )}
      </Stack>

      <Text size="xs" c="dimmed">
        Saving adds a new choice written by you. The request and the prompt of
        this shot are then worked out again from it, except a prompt you wrote
        yourself, which stays as it is and says it is out of date.
      </Text>
      <EditorActions
        saving={saving}
        error={error}
        errorTitle="Could not save the references"
        canSave={chosen.length >= 1 && chosen.length <= H3_MAX_REFERENCES}
        onSave={() => onSave(chosen)}
        onCancel={onCancel}
      />
    </Stack>
  );
}
