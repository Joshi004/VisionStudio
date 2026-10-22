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
  const view = picture.kind === "environment" ? "place" : humanize(picture.view);
  const variant =
    picture.variant === "default" ? "" : `, ${humanize(picture.variant)}`;
  return `${picture.subject_name}: ${view}${variant}`;
}
