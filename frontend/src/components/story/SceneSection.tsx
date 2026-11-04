import type { ReactNode } from "react";
import { Badge, Button, Group, Loader, Stack, Text } from "@mantine/core";

import { RunSceneButton } from "./RunSceneButton";

type SceneSectionProps = {
  /** The scene's number, shown in front of its title. */
  index: number;
  title: string;
  /** Where the scene's shots stand (counts), shown beside the title. Always visible. */
  badges: ReactNode;
  /** A line or two under the title that stay visible while the scene is closed. */
  note?: ReactNode;
  /** The scene's own buttons (for example "Generate scene"). They do not open or close it. */
  actions?: ReactNode;
  /** Adds "Run this scene" before the scene's own buttons (SCN-004). */
  runScene?: { projectId: number; sceneId: string };
  opened: boolean;
  onToggle: () => void;
  /** True while the open scene's shots are being loaded. */
  loading?: boolean;
  /** What the toggle button calls the content, for example "shots" or "takes". */
  noun?: string;
  /** The scene's content. It is rendered only while the scene is open. */
  children: ReactNode;
};

/**
 * One scene of a shot list. It is closed until it is opened, and a closed scene renders no
 * shots at all (they are not even loaded), only its title and the counts in `badges`. A page
 * keeps one scene open at a time.
 */
export function SceneSection({
  index,
  title,
  badges,
  note,
  actions,
  runScene,
  opened,
  onToggle,
  loading = false,
  noun = "shots",
  children,
}: SceneSectionProps) {
  return (
    <Stack gap={6}>
      <Group align="flex-start" wrap="nowrap" gap="sm">
        <Badge
          variant="outline"
          color="gray"
          miw={40}
          style={{ flexShrink: 0, textTransform: "none" }}
        >
          {index}
        </Badge>
        <Stack gap={4} style={{ flexGrow: 1 }}>
          <Group gap="xs">
            <Text
              size="sm"
              fw={500}
              onClick={onToggle}
              style={{ cursor: "pointer" }}
            >
              {title}
            </Text>
            {badges}
          </Group>
          {note}
        </Stack>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {runScene !== undefined && (
            <RunSceneButton
              projectId={runScene.projectId}
              sceneId={runScene.sceneId}
              sceneLabel={`Scene ${index}: ${title}`}
            />
          )}
          {actions}
          <Button
            size="compact-sm"
            variant="subtle"
            aria-expanded={opened}
            onClick={onToggle}
          >
            {opened ? `Hide ${noun}` : `Show ${noun}`}
          </Button>
        </Group>
      </Group>
      {opened && (
        <Stack gap="sm" ml={48}>
          {loading ? <Loader size="sm" /> : children}
        </Stack>
      )}
    </Stack>
  );
}
