import { createReadStream } from "node:fs";
import Fastify from "fastify";

import { counts, enqueue, fileOf, MAX_PARALLEL, prepareRenderDir, remove, statusOf, sweep } from "./renders.ts";
import { checkComponent, ServiceError } from "./checks.ts";
import { measureLayout } from "./layout.ts";
import { checksRequestSchema, idParamsSchema, layoutRequestSchema, renderRequestSchema } from "./schema.ts";
import type { ChecksRequest, LayoutRequest, RenderRequest } from "./schema.ts";
import { BLOCKS_VERSION } from "../blocks/scene.ts";
import { GENERATED_VERSION } from "../generated/version.ts";
import { CATALOGUE_VERSION } from "../templates/spec.ts";
import { readVersions } from "./versions.ts";

const PORT = Number(process.env["PORT"] ?? 8090);
const BODY_LIMIT_BYTES = 1024 * 1024;

const versions = readVersions();
prepareRenderDir();

const app = Fastify({
  // The request log carries the method, address and time only, never a body.
  logger: { level: "info" },
  bodyLimit: BODY_LIMIT_BYTES,
});

// What the service is made of.
app.get("/health", async () => ({
  ok: true,
  remotion: versions.remotion,
  chrome: versions.chrome,
  node: process.version,
  templates: CATALOGUE_VERSION,
  blocks: BLOCKS_VERSION,
  generated: GENERATED_VERSION,
  max_parallel: MAX_PARALLEL,
  ...counts(),
}));

app.post<{ Body: RenderRequest }>(
  "/renders",
  { schema: { body: renderRequestSchema } },
  async (request, reply) => {
    const renderId = enqueue(request.body);
    return reply.code(202).send({ render_id: renderId });
  },
);

// The texts of a block scene as the browser lays them out, at the frames asked for (GFX-009).
app.post<{ Body: LayoutRequest }>(
  "/layout",
  { schema: { body: layoutRequestSchema } },
  async (request, reply) => {
    try {
      return await measureLayout(request.body);
    } catch (error) {
      const text = error instanceof Error ? error.message : String(error);
      return reply.code(422).send({ error: text.slice(0, 2000) });
    }
  },
);

// Transpiles a generated component and draws still frames of it: three, or the up to 16 the request
// names (GFX-010, EXG-006). A component that
// does not compile or does not draw is a 200 with `ok: false` and the errors; only a service that
// cannot run the check at all answers 422.
app.post<{ Body: ChecksRequest }>(
  "/checks",
  { schema: { body: checksRequestSchema } },
  async (request, reply) => {
    try {
      return await checkComponent(request.body);
    } catch (error) {
      if (!(error instanceof ServiceError)) throw error;
      return reply.code(422).send({ error: error.message });
    }
  },
);

app.get<{ Params: { id: string } }>(
  "/renders/:id",
  { schema: { params: idParamsSchema } },
  async (request, reply) => {
    const status = statusOf(request.params.id);
    return status ?? reply.code(404).send({ error: "No render has this id." });
  },
);

app.get<{ Params: { id: string } }>(
  "/renders/:id/file",
  { schema: { params: idParamsSchema } },
  async (request, reply) => {
    const file = fileOf(request.params.id);
    if (file === null) return reply.code(404).send({ error: "The render has no finished file." });
    return reply
      .header("Content-Type", "video/mp4")
      .header("Content-Length", String(file.size))
      .send(createReadStream(file.path));
  },
);

app.delete<{ Params: { id: string } }>(
  "/renders/:id",
  { schema: { params: idParamsSchema } },
  async (request, reply) => {
    if (!remove(request.params.id)) return reply.code(404).send({ error: "No render has this id." });
    return reply.code(204).send();
  },
);

setInterval(() => sweep(), 60_000).unref();

// Closing a browser while Remotion is still closing one of its pages (a component that threw or hung,
// GFX-010) makes Remotion reject a promise nobody awaits, and Node would stop the whole service for
// it. Only that one error is let through; anything else still stops the process.
process.on("unhandledRejection", (reason) => {
  const text = reason instanceof Error ? reason.message : String(reason);
  if (text.includes("Target closed")) {
    app.log.warn("a closing browser page was cut short (ignored)");
    return;
  }
  throw reason;
});

const shutdown = () => {
  void app.close().finally(() => process.exit(0));
};
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

await app.listen({ host: "0.0.0.0", port: PORT });
