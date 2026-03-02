#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { createHash } from "node:crypto";
import { z } from "zod";

// ============================================================================
// Config
// ============================================================================

const QDRANT_URL = process.env.QDRANT_URL ?? "http://localhost:6333";
const OLLAMA_URL = process.env.OLLAMA_URL ?? "http://localhost:11434";
const EMBEDDING_MODEL = process.env.EMBEDDING_MODEL ?? "snowflake-arctic-embed2";
const COLLECTION_NAME = process.env.COLLECTION_NAME ?? "memories_tr";

const MCP_AUTH_TOKEN = process.env.MCP_AUTH_TOKEN ?? "";

const MEMORY_CATEGORIES = [
  "preference", "fact", "decision", "entity",
  "architecture", "solution", "todo", "other",
] as const;

// ============================================================================
// Helpers
// ============================================================================

function deterministicPointId(text: string): number {
  const hash = createHash("sha256").update(text).digest();
  const bigId = hash.readBigUInt64BE(0) % BigInt(Number.MAX_SAFE_INTEGER);
  return Number(bigId);
}

async function ollamaEmbed(text: string): Promise<number[] | null> {
  try {
    const resp = await fetch(`${OLLAMA_URL}/api/embeddings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: EMBEDDING_MODEL, prompt: text }),
      signal: AbortSignal.timeout(15_000),
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    return data.embedding;
  } catch {
    return null;
  }
}

async function qdrantSearch(
  vector: number[],
  limit: number,
  minScore: number,
): Promise<any[]> {
  try {
    const resp = await fetch(
      `${QDRANT_URL}/collections/${COLLECTION_NAME}/points/search`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vector,
          limit,
          with_payload: true,
          score_threshold: minScore,
        }),
        signal: AbortSignal.timeout(10_000),
      },
    );
    if (!resp.ok) return [];
    const data = await resp.json();
    return data.result ?? [];
  } catch {
    return [];
  }
}

async function qdrantUpsert(
  pointId: number,
  vector: number[],
  payload: Record<string, unknown>,
): Promise<boolean> {
  try {
    const resp = await fetch(
      `${QDRANT_URL}/collections/${COLLECTION_NAME}/points`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          points: [{ id: pointId, vector, payload }],
        }),
        signal: AbortSignal.timeout(10_000),
      },
    );
    return resp.ok;
  } catch {
    return false;
  }
}

async function qdrantDelete(pointIds: number[]): Promise<boolean> {
  try {
    const resp = await fetch(
      `${QDRANT_URL}/collections/${COLLECTION_NAME}/points/delete`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ points: pointIds }),
        signal: AbortSignal.timeout(10_000),
      },
    );
    return resp.ok;
  } catch {
    return false;
  }
}

async function qdrantScroll(
  limit: number,
  orderBy: string,
): Promise<any[]> {
  try {
    const resp = await fetch(
      `${QDRANT_URL}/collections/${COLLECTION_NAME}/points/scroll`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          limit,
          with_payload: true,
          order_by: { key: orderBy, direction: "desc" },
        }),
        signal: AbortSignal.timeout(10_000),
      },
    );
    if (!resp.ok) return [];
    const data = await resp.json();
    return data.result?.points ?? [];
  } catch {
    return [];
  }
}

// ============================================================================
// MCP Server
// ============================================================================

function createServer(): McpServer {
const server = new McpServer({
  name: "truerecall",
  version: "1.0.0",
});

// -- memory_search -----------------------------------------------------------

server.tool(
  "memory_search",
  "Semantic search over TrueRecall long-term memories. Returns the most relevant memories for a query, ranked by similarity.",
  {
    query: z.string().describe("Search query text"),
    limit: z.number().int().min(1).max(50).default(5).describe("Max results to return"),
    min_score: z.number().min(0).max(1).default(0.4).describe("Minimum similarity score threshold"),
  },
  async ({ query, limit, min_score }) => {
    const vector = await ollamaEmbed(query);
    if (!vector) {
      return {
        content: [{ type: "text" as const, text: "Error: Ollama embedding service unavailable. Is Ollama running?" }],
        isError: true,
      };
    }

    const results = await qdrantSearch(vector, limit, min_score);
    if (results.length === 0) {
      return {
        content: [{ type: "text" as const, text: "No relevant memories found." }],
      };
    }

    const lines = results.map((pt: any, i: number) => {
      const text = pt.payload?.text ?? pt.payload?.content ?? "";
      const category = pt.payload?.category ?? "other";
      const importance = pt.payload?.importance ?? 0.5;
      const timestamp = pt.payload?.timestamp ?? "";
      const score = (pt.score ?? 0).toFixed(3);
      return `${i + 1}. [${category}] ${text}\n   id=${pt.id} importance=${importance} score=${score} time=${timestamp}`;
    });

    return {
      content: [{
        type: "text" as const,
        text: `Found ${results.length} memories:\n\n${lines.join("\n\n")}`,
      }],
    };
  },
);

// -- memory_store ------------------------------------------------------------

server.tool(
  "memory_store",
  "Store a new memory in TrueRecall. Use for preferences, facts, decisions, architecture notes, or anything worth remembering long-term.",
  {
    text: z.string().describe("The memory text to store"),
    category: z.enum(MEMORY_CATEGORIES).default("other").describe("Memory category"),
    importance: z.number().min(0).max(1).default(0.7).describe("Importance score (0-1)"),
  },
  async ({ text, category, importance }) => {
    const vector = await ollamaEmbed(text);
    if (!vector) {
      return {
        content: [{ type: "text" as const, text: "Error: Ollama embedding service unavailable." }],
        isError: true,
      };
    }

    // Dedup check — reject if a very similar memory already exists
    const existing = await qdrantSearch(vector, 1, 0.95);
    if (existing.length > 0) {
      const existingText = existing[0].payload?.text ?? existing[0].payload?.content ?? "";
      return {
        content: [{
          type: "text" as const,
          text: `Similar memory already exists (id=${existing[0].id}): "${existingText.slice(0, 120)}"`,
        }],
      };
    }

    const pointId = deterministicPointId(text);
    const success = await qdrantUpsert(pointId, vector, {
      text,
      content: text,
      category,
      importance,
      timestamp: new Date().toISOString(),
      source: "truerecall-mcp",
      curated: true,
      user_id: "ava",
    });

    if (!success) {
      return {
        content: [{ type: "text" as const, text: "Error: Failed to store memory. Qdrant may be unavailable." }],
        isError: true,
      };
    }

    return {
      content: [{
        type: "text" as const,
        text: `Stored memory (id=${pointId}, category=${category}, importance=${importance}): "${text.slice(0, 120)}"`,
      }],
    };
  },
);

// -- memory_recent -----------------------------------------------------------

server.tool(
  "memory_recent",
  "Get the most recent memories by timestamp. Useful for reviewing what was recently stored.",
  {
    limit: z.number().int().min(1).max(100).default(10).describe("Number of recent memories to return"),
  },
  async ({ limit }) => {
    const points = await qdrantScroll(limit, "timestamp");
    if (points.length === 0) {
      return {
        content: [{ type: "text" as const, text: "No memories found." }],
      };
    }

    const lines = points.map((pt: any, i: number) => {
      const text = pt.payload?.text ?? pt.payload?.content ?? "";
      const category = pt.payload?.category ?? "other";
      const importance = pt.payload?.importance ?? 0.5;
      const timestamp = pt.payload?.timestamp ?? "";
      return `${i + 1}. [${category}] ${text}\n   id=${pt.id} importance=${importance} time=${timestamp}`;
    });

    return {
      content: [{
        type: "text" as const,
        text: `${points.length} most recent memories:\n\n${lines.join("\n\n")}`,
      }],
    };
  },
);

// -- memory_delete -----------------------------------------------------------

server.tool(
  "memory_delete",
  "Delete a memory by its point ID. Use memory_search first to find the ID of the memory to delete.",
  {
    id: z.number().describe("The point ID of the memory to delete"),
  },
  async ({ id }) => {
    const success = await qdrantDelete([id]);
    if (!success) {
      return {
        content: [{ type: "text" as const, text: `Error: Failed to delete memory ${id}. Qdrant may be unavailable.` }],
        isError: true,
      };
    }

    return {
      content: [{ type: "text" as const, text: `Deleted memory (id=${id}).` }],
    };
  },
);

return server;
}

// Create default instance for stdio mode
const server = createServer();

// ============================================================================
// Start
// ============================================================================

async function ensureTimestampIndex(): Promise<void> {
  try {
    const resp = await fetch(
      `${QDRANT_URL}/collections/${COLLECTION_NAME}/index`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          field_name: "timestamp",
          field_schema: "datetime",
        }),
        signal: AbortSignal.timeout(5_000),
      },
    );
    // 200 = created, 400 = already exists — both fine
    if (!resp.ok && resp.status !== 400) {
      console.error(`Warning: could not ensure timestamp index (${resp.status})`);
    }
  } catch {
    // Non-fatal — memory_recent will just return empty
  }
}

const TRANSPORT = process.env.MCP_TRANSPORT ?? "stdio";
const PORT = parseInt(process.env.MCP_PORT ?? "3100", 10);
const HOST = process.env.MCP_HOST ?? "0.0.0.0";

async function startStdio() {
  await ensureTimestampIndex();
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

async function startSSE() {
  await ensureTimestampIndex();

  const { default: express } = await import("express");
  const app = express();
  app.use(express.json());

  // Auth middleware — skip health check and authenticated sessions
  if (MCP_AUTH_TOKEN) {
    app.use((req, res, next) => {
      if (req.path === "/health") return next();
      // Allow /messages through if the session is already established (authenticated at /sse)
      if (req.path === "/messages" && req.query.sessionId && transports[req.query.sessionId as string]) {
        return next();
      }
      const auth = req.headers.authorization;
      const queryToken = req.query.token as string | undefined;
      if (auth === `Bearer ${MCP_AUTH_TOKEN}` || queryToken === MCP_AUTH_TOKEN) {
        return next();
      }
      res.status(401).json({ error: "Unauthorized" });
      return;
    });
    console.log("Authentication enabled (MCP_AUTH_TOKEN set)");
  } else {
    console.log("⚠️  No MCP_AUTH_TOKEN set — server is unauthenticated!");
  }

  // Store transports by session ID
  const transports: Record<string, SSEServerTransport> = {};

  // SSE endpoint — client GETs this to open the event stream
  app.get("/sse", async (req, res) => {
    const transport = new SSEServerTransport("/messages", res);
    const sessionId = transport.sessionId;
    transports[sessionId] = transport;

    transport.onclose = () => {
      delete transports[sessionId];
    };

    // Create a fresh server instance per session
    const sessionServer = createServer();
    await sessionServer.connect(transport);
    console.log(`SSE session established: ${sessionId}`);
  });

  // Messages endpoint — client POSTs JSON-RPC here
  app.post("/messages", async (req, res) => {
    const sessionId = req.query.sessionId as string;
    if (!sessionId || !transports[sessionId]) {
      res.status(404).send("Session not found");
      return;
    }
    await transports[sessionId].handlePostMessage(req, res, req.body);
  });

  // Health check
  app.get("/health", (_req, res) => {
    res.json({ status: "ok", transport: "sse", sessions: Object.keys(transports).length });
  });

  app.listen(PORT, HOST, () => {
    console.log(`TrueRecall MCP Server (SSE) listening on http://${HOST}:${PORT}`);
    console.log(`  SSE endpoint:      GET  http://${HOST}:${PORT}/sse`);
    console.log(`  Messages endpoint: POST http://${HOST}:${PORT}/messages`);
    console.log(`  Health check:      GET  http://${HOST}:${PORT}/health`);
  });

  process.on("SIGINT", async () => {
    for (const sid of Object.keys(transports)) {
      await transports[sid].close();
      delete transports[sid];
    }
    process.exit(0);
  });
}

async function main() {
  if (TRANSPORT === "sse" || TRANSPORT === "http") {
    await startSSE();
  } else {
    await startStdio();
  }
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
