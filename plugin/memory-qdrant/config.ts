import { Type, Static } from '@sinclair/typebox';

export const ConfigSchema = Type.Object({
  qdrantUrl: Type.String({
    default: 'http://localhost:6333',
    description: 'Qdrant server URL'
  }),
  ollamaUrl: Type.String({
    default: 'http://localhost:11434',
    description: 'Ollama server URL'
  }),
  embeddingModel: Type.String({
    default: 'snowflake-arctic-embed2',
    description: 'Ollama embedding model name'
  }),
  collection: Type.String({
    default: 'memories_tr',
    description: 'Qdrant collection name'
  }),
  vectorDim: Type.Integer({
    default: 1024,
    description: 'Vector dimensions'
  }),
  autoRecall: Type.Boolean({
    default: true,
    description: 'Automatically recall relevant memories before agent start'
  }),
  autoCapture: Type.Boolean({
    default: false,
    description: 'Automatically capture important memories after conversation'
  }),
  minScore: Type.Number({
    default: 0.4,
    minimum: 0,
    maximum: 1,
    description: 'Minimum similarity score for memory recall'
  }),
  maxResults: Type.Integer({
    default: 5,
    minimum: 1,
    description: 'Maximum number of memories to recall'
  })
});

export type Config = Static<typeof ConfigSchema>;

export const defaultConfig: Config = {
  qdrantUrl: 'http://localhost:6333',
  ollamaUrl: 'http://localhost:11434',
  embeddingModel: 'snowflake-arctic-embed2',
  collection: 'memories_tr',
  vectorDim: 1024,
  autoRecall: true,
  autoCapture: false,
  minScore: 0.4,
  maxResults: 5
};