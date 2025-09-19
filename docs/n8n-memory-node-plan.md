# Memscend n8n Memory Node – Design Notes

## Motivation

n8n’s Agent `Memory` socket only supports nodes implementing the `IMemory` contract. The built-ins target simple storage (in-memory, Redis, MongoDB, Postgres, Motorhead, Xata). None match Memscend’s multi-tenant vector store. We need a first-class node that bridges the Agent workflow with our REST/MCP APIs.

## Reference: Existing memory nodes (n8n v1.30+)

| Node                 | Storage model                      | Key features                                               | Lessons |
|----------------------|-------------------------------------|------------------------------------------------------------|---------|
| Simple Memory        | In-memory (workflow state)         | Zero setup, ephemeral per execution                       | Optional for fallback; not persistent |
| Motorhead Memory     | Motorhead REST API                 | Persistent, instructions for summarization                | Similar REST structure; use as structural reference |
| MongoDB Chat Memory  | MongoDB collection                 | Schema-based (messages, metadata)                         | Good for credential handling, pagination |
| Postgres Chat Memory | Postgres table                     | SQL storage w/ pruning                                    | Shows how to implement configurable cleanup |
| Redis Chat Memory    | Redis list                         | TTL, upsert, quick retrieval                              | Emphasizes TTL configuration |
| Xata Memory          | SaaS vector store                  | Vector similarity & metadata                              | Similar to Memscend, ensure vector queries optional |
| Pinecone/Weaviate (MCP via n8n nodes) | Vector DB wrappers | Embedding + search                                         | Workflow for embedding generation |

## Requirements for Memscend Memory Node

1. **Transport options**
   - HTTP REST (preferred)
   - Optional MCP SSE/stdio via proxy (future)

2. **Operations**
   - `init`: configure tenant (org_id, agent_id, user_id, API base, secret)
   - `loadMemoryVariables`: call `GET /api/v1/mem/list` + `search` for context
   - `saveContext`: ingest via `POST /api/v1/mem/add`
   - `clear`: use batch delete soft OR `hard=true`
   - Optional `vectorSearch`: `GET /api/v1/mem/search`

3. **Agent hooks** (n8n IMemory interface)
   - store & load data as key/value (expected by Agent nodes)
   - maintain conversation history field names consistent with existing nodes

4. **Configuration options**
   - Credentials: base URL, shared secret, org_id, agent_id, default user_id
   - Scope filters: tags, scopes to include/exclude
   - Write policy toggles: dedupe check? TTL override? (exposed as advanced options)
   - `maxResults`, `includeDeleted`

5. **Error handling**
   - Propagate Memscend error messages
   - Retry logic (configurable) similar to Motorhead node

6. **Documentation**
   - README update with usage steps
   - Example workflows (load/add/clear)

### Data flow

1. `loadMemoryVariables` (Agent pulls context)
   - Call `list_memories` (recent) + `search_memory` (optional by query/topic)
   - Format into `history` array consumed by Agent node (role/content pairs)

2. `saveContext`
   - Receive `input` + `output`
   - Build MemoryAddRequest (messages) mapping conversation to our schema
   - Optionally include `tags`, `scope` as node options

3. `clear`
   - Use `delete_memories` with soft or hard delete depending on settings

### Implementation outline

1. **Repo/Package structure**
   - Create `packages/n8n-nodes-memscend-memory`
   - Follow n8n community node template (tsconfig, package.json)
   - Node class extends `IMemory` contract

2. **Credentials**
   - Custom credentials JSON with fields: `baseUrl`, `sharedSecret`, `orgId`, `agentId`, `userId`, optional `headers`

3. **Node class**
   - Methods: `init`, `loadMemoryVariables`, `saveContext`, `clear` per n8n docs
   - Use Axios or native fetch for HTTP

4. **Testing**
   - Leverage n8n node unit test harness or simple integration tests (hit local Memscend instance with mock data)

5. **Distribution**
   - Publish to npm (`@memscend/n8n-nodes-memory`), document `N8N_COMMUNITY_PACKAGES_ALLOW_TOOL_USAGE`

## Next steps

1. Implement the node following template
2. Add README section linking to package & configuration instructions
3. Provide sample n8n workflow JSON
