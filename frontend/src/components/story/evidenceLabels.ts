/** Words and colours for a claim's status, shared by the import report and the review. */
export const CLAIM_STATUS_LABEL: Record<string, string> = {
  found: "Found",
  partial: "Partly found",
  not_found: "Not found",
  contradicted: "Contradicted",
  blocked: "Blocked",
  no_result: "No result",
  invalid: "Unusable result",
};

export const CLAIM_STATUS_COLOR: Record<string, string> = {
  found: "green",
  partial: "yellow",
  not_found: "gray",
  contradicted: "red",
  blocked: "orange",
  no_result: "gray",
  invalid: "red",
};
