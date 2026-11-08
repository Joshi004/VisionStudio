import { Typography } from "@mantine/core";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/** Links open in a new tab and never hand the page to the site they point to. */
const COMPONENTS: Components = {
  a: ({ href, title, children }) => (
    <a href={href} title={title} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
};

/**
 * A model's answer shown as formatted text: headings, lists, tables, code, links and the rest
 * of GitHub-style markdown. Raw HTML in the answer is not rendered (react-markdown shows it as
 * text), and unsafe link addresses such as `javascript:` are removed by react-markdown itself.
 */
export function MarkdownText({ children }: { children: string }) {
  return (
    <Typography>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    </Typography>
  );
}
