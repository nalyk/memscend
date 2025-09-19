# n8n Memscend Memory Node

Memscend is a multi-tenant memory service built on OpenRouter, TEI, and Qdrant. This community package plugs Memscend into n8n's Agent "Memory" socket so workflows can persist and recall memories through the existing Memscend HTTP API.

## Features

- Read recent memories via `/api/v1/mem/list`
- Write new observations with `/api/v1/mem/add`
- Soft-delete memories in bulk
- Tenant-aware: org, agent, and user IDs per credentials
- Optional tags and scoped writes (`facts`, `prefs`, `persona`, `constraints`)

## Installation

1. Enable community packages in n8n:
   ```bash
   export N8N_COMMUNITY_PACKAGES_ALLOW_TOOL_USAGE=true
   ```
2. Install the package:
   ```bash
   npm install @memscend/n8n-nodes-memscend-memory
   ```
3. Restart n8n. The "Memscend Memory" node appears under the Memory section of the Agent panel.

## Credentials

Create a new credential of type **Memscend API** and fill in:
- Base URL (e.g. `http://127.0.0.1:8080`)
- Shared secret (from `.env`)
- Organisation ID & Agent ID
- Optional default User ID (overrideable per workflow)
- Additional headers if required

## Usage

1. Add the **Memscend Memory** node in the Agent's Memory slot.
2. Configure scope (`facts` by default) and optional tags.
3. Run the workflow: the node loads recent memories into the agent context and stores new outputs after each step.

## Build

```bash
npm run build
```

## Publish

```bash
npm publish --access public
```

## License

MIT
