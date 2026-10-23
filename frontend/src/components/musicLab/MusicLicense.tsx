import { Badge, Group, Text } from "@mantine/core";

import type { MusicModelInfo } from "../../api/musicLab";
import { LICENSE_COLORS, LICENSE_LABELS } from "./musicLabView";

/** The licence of a music model as a coloured badge. Its note is the badge's tooltip text. */
export function LicenseBadge({ model }: { model: Pick<MusicModelInfo, "license_level" | "license_note"> }) {
  return (
    <Badge
      color={LICENSE_COLORS[model.license_level]}
      variant="light"
      title={model.license_note}
      style={{ cursor: "help" }}
    >
      {LICENSE_LABELS[model.license_level]}
    </Badge>
  );
}

/**
 * The warning for a model: shown wherever the app makes sound with it. A model that is open
 * shows nothing, because there is nothing to be careful about.
 */
export function LicenseNotice({ model }: { model: Pick<MusicModelInfo, "license_level" | "license_note"> }) {
  if (model.license_level === "open") {
    return null;
  }
  return (
    <Group gap={6} wrap="nowrap" align="flex-start">
      <LicenseBadge model={model} />
      <Text size="xs" c={model.license_level === "non_commercial" ? "red.8" : "orange.8"}>
        {model.license_note}
      </Text>
    </Group>
  );
}
