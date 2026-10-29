import { Fragment } from "react";
import { Text } from "@mantine/core";

import { partIndexOfWord, wordsOf, type AvPart } from "./avLabView";

/** One colour for each part, in turn, so two parts side by side can be told apart. */
const PART_COLORS = [
  "var(--mantine-color-blue-2)",
  "var(--mantine-color-teal-2)",
  "var(--mantine-color-grape-2)",
  "var(--mantine-color-orange-2)",
];

type AvMarkedTextProps = {
  text: string;
  parts: readonly AvPart[];
  /** Called with the number of the word that was clicked, when given. */
  onWordClick?: (word: number) => void;
};

/**
 * The text with the words of each marked part highlighted and numbered by colour. The spaces and
 * line breaks of the text are kept as they are. With `onWordClick`, a marked word can be clicked
 * (the form removes its part).
 */
export function AvMarkedText({ text, parts, onWordClick }: AvMarkedTextProps) {
  const words = wordsOf(text);
  return (
    <Text size="sm" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
      {words.map((word, index) => {
        const gap = text.slice(index === 0 ? 0 : words[index - 1].end, word.start);
        const part = partIndexOfWord(parts, index);
        const marked = part >= 0;
        return (
          <Fragment key={word.start}>
            {gap}
            <span
              title={
                marked
                  ? onWordClick
                    ? `Part ${part + 1}. Click to remove it.`
                    : `Part ${part + 1}`
                  : undefined
              }
              onClick={marked && onWordClick ? () => onWordClick(index) : undefined}
              style={{
                background: marked ? PART_COLORS[part % PART_COLORS.length] : undefined,
                borderRadius: 3,
                padding: marked ? "0 1px" : undefined,
                cursor: marked && onWordClick ? "pointer" : undefined,
              }}
            >
              {word.text}
            </span>
          </Fragment>
        );
      })}
    </Text>
  );
}
