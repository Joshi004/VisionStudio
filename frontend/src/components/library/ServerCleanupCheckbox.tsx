import { Checkbox } from "@mantine/core";

type ServerCleanupCheckboxProps = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
};

/**
 * The choice, in every delete dialog, to also clean up the GPU server. It is never ticked for the
 * user: the dialog keeps the value in its own state and starts it unticked each time it opens.
 */
export function ServerCleanupCheckbox({ checked, onChange, disabled }: ServerCleanupCheckboxProps) {
  return (
    <Checkbox
      checked={checked}
      disabled={disabled}
      onChange={(event) => onChange(event.currentTarget.checked)}
      label="Also delete what is left on the GPU server"
      description="Best effort, done after the deletion. Jobs stay on the server until it removes them itself, so this frees them (and their logs) sooner."
    />
  );
}
