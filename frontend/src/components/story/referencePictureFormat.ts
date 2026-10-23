/** The fields of a reference picture (chosen or in the catalog) that its label is made from. */
export type PictureLike = {
  kind: string;
  view: string;
  variant: string;
  subject_name: string;
};

export function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

/** What a picture is, in a few words: whose, which angle, which look or state. */
export function pictureLabel(picture: PictureLike): string {
  // The master picture of a place has the view `environment`; its other views have a name of
  // their own (PHASE-054).
  const view =
    picture.kind !== "environment"
      ? humanize(picture.view)
      : picture.view === "environment"
        ? "place"
        : `place, ${humanize(picture.view)} view`;
  const variant =
    picture.variant === "default" ? "" : `, ${humanize(picture.variant)}`;
  return `${picture.subject_name}: ${view}${variant}`;
}
