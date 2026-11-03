import { transform } from "esbuild";
import type { TransformFailure } from "esbuild";

export type Transpiled = { js: string; error?: undefined } | { js?: undefined; error: string };

function isFailure(error: unknown): error is TransformFailure {
  return typeof error === "object" && error !== null && Array.isArray((error as TransformFailure).errors);
}

// Turns the model's TSX into CommonJS that the `Generated` composition can evaluate (GFX-010). The
// automatic JSX transform imports `react/jsx-runtime`, which the composition's `require` knows.
// An error names the line and column of the first problem, which goes back to the model.
export async function transpile(code: string): Promise<Transpiled> {
  try {
    const result = await transform(code, {
      loader: "tsx",
      format: "cjs",
      jsx: "automatic",
      target: "es2022",
      sourcefile: "component.tsx",
      logLevel: "silent",
    });
    return { js: result.code };
  } catch (error) {
    if (isFailure(error) && error.errors.length > 0) {
      const messages = error.errors.slice(0, 5).map((item) => {
        const where = item.location ? `line ${item.location.line}, column ${item.location.column}: ` : "";
        return `${where}${item.text}`;
      });
      return { error: messages.join("\n").slice(0, 2000) };
    }
    return { error: (error instanceof Error ? error.message : String(error)).slice(0, 2000) };
  }
}
