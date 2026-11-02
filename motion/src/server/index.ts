import { createReadStream } from "node:fs";
import Fastify from "fastify";

import { counts, enqueue, fileOf, MAX_PARALLEL, prepareRenderDir, remove, statusOf, sweep } from "./renders.ts";
import { idParamsSchema, renderRequestSchema } from "./schema.ts";
import type { RenderRequest } from "./schema.ts";
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

// What the service is made of. The template catalogue and the block library have no version
// until GFX-006 and GFX-009.
app.get("/health", async () => ({
  ok: true,
  remotion: versions.remotion,
  chrome: versions.chrome,
  node: process.version,
  templates: null,
  blocks: null,
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

const shutdown = () => {
  void app.close().finally(() => process.exit(0));
};
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

await app.listen({ host: "0.0.0.0", port: PORT });
