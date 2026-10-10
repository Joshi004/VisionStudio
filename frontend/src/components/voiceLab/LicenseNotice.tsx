import { Text } from "@mantine/core";

/**
 * The licence of the speech model, shown wherever the app makes speech with it. Breeze TTS 2's
 * weights, and what they produce when self-hosted, are for research and non-commercial use.
 */
export function LicenseNotice() {
  return (
    <Text size="xs" c="orange.8">
      Breeze TTS 2 is licensed for research and non-commercial use only. Only clone a voice you
      have the right and the consent to use.
    </Text>
  );
}
