/**
 * A lower-case id made from a name ("The Cellar" gives "the_cellar"), different from the ids in
 * `taken`. It only fills in a new row's id: the user can change it until the row is saved.
 */
export function slugFromName(name: string, taken: readonly string[]): string {
  const words = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const stem = /^[a-z]/.test(words) ? words.slice(0, 40) : "item";
  if (!taken.includes(stem)) {
    return stem;
  }
  let number = 2;
  while (taken.includes(`${stem}_${number}`)) {
    number += 1;
  }
  return `${stem}_${number}`;
}
