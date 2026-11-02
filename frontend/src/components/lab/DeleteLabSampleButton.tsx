import { useState } from "react";
import { Button } from "@mantine/core";

import type { LabSampleKind } from "../../api/deletion";
import { DeleteLabSampleModal } from "./DeleteLabSampleModal";

type DeleteLabSampleButtonProps = {
  kind: LabSampleKind;
  sampleId: number;
  /** Called after the sample was deleted, for example to close the view that showed it. */
  onDeleted?: () => void;
};

/** A small Delete button for one lab sample. It opens the dialog that asks before deleting. */
export function DeleteLabSampleButton({ kind, sampleId, onDeleted }: DeleteLabSampleButtonProps) {
  const [asking, setAsking] = useState(false);
  return (
    <>
      <Button size="compact-xs" variant="subtle" color="red" onClick={() => setAsking(true)}>
        Delete
      </Button>
      {asking && (
        <DeleteLabSampleModal
          kind={kind}
          sampleId={sampleId}
          onClose={() => setAsking(false)}
          onDeleted={onDeleted}
        />
      )}
    </>
  );
}
