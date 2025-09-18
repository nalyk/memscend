**TL;DR:** Blueprint tehnic complet pentru „Memory Service” multi-tenant: LLM remote prin **OpenRouter**, embeddings locale cu **EmbeddingGemma 300M** servit prin **Hugging Face TEI**, stocare în **Qdrant**. Expunere dublă: **MCP (SSE)** pentru clienți compatibili și **HTTP (REST + SSE/NDJSON)** pentru orchestratoare. Include topologie, flow-uri, contracte, securitate, observabilitate, tuning HNSW, deployment pe un VPS mic (DO), migrare, testare și runbook. Referințe critice marcate în text.

---

# Blueprint tehnic — „Memory Service” (OpenRouter + EmbeddingGemma/TEI + Qdrant; MCP + HTTP)

## 1) Vedere de ansamblu

**Obiectiv:** un serviciu de memorie persistentă, multi-tenant, cu regăsire semantică rapidă și interfațe standardizate.
**Stack:**

* **Generative (remote):** OpenRouter, API OpenAI-compat, rutare/fallback la mai multe modele. ([OpenRouter][1])
* **Embeddings (local):** EmbeddingGemma 300M, dimensiune implicită **768**, opțiuni MRL 512/256/128; servit de **Text Embeddings Inference (TEI)**. ([Hugging Face][2])
* **Vector DB:** Qdrant, index HNSW cu tuning m/ef și opțiune on-disk pentru VPS modest. ([Qdrant][3])
* **Expunere:**

  * **MCP (SSE)** pentru IDE-uri/agenți compatibili (Claude Desktop, Cursor, etc.). ([Model Context Protocol][4])
  * **HTTP** (REST + streaming SSE/NDJSON) pentru n8n, boți, webhooks.

## 2) Topologie de deployment (VPS DigitalOcean)

**Roluri pe un singur droplet** (ex. 2 vCPU/4–8 GB RAM):

* container **tei-embed**: TEI cu `google/embeddinggemma-300m` pe `:3000`
* container **qdrant**: Qdrant pe `:6333/6334`
* **memory-core**: serviciu Python care folosește Mem0 ca layer logic (add/search), conectat la OpenRouter + TEI + Qdrant
* **gateways**:

  * **http-gw**: FastAPI pentru REST + SSE/NDJSON
  * **mcp-gw**: server MCP (SSE) cu tool-uri `add_memories`, `search_memory`, `update`, `delete`

Opțional: **Nginx** în față pentru TLS și timeouts corecte pentru SSE.

## 3) Fluxuri principale

### 3.1 Scriere memorie (ingest)

1. Clientul (MCP sau HTTP) trimite text + metadate: `org_id`, `agent_id`, `user_id`, `scope`, `tags`.
2. **Core** aplică „write policy” (criterii, dedup, merge).
3. **Generative**: OpenRouter produce extrageri/normalizări dacă e nevoie de „curățare” textuală. ([OpenRouter][1])
4. **Embeddings**: TEI encodează în vector de **768** (sau redus MRL). ([Hugging Face][2])
5. **Qdrant**: inserție în colecția corectă; payload include toți identificatorii + TTL.

### 3.2 Căutare semantică (read)

1. Clientul trimite `query` + filtru obligatoriu de tenanță (`org_id`, `agent_id`).
2. Core encodează interogarea cu TEI.
3. Qdrant: HNSW cosine top-k + filtre payload; opțional time-decay și diversitate. ([Qdrant][3])
4. Rezultatele sunt returnate pe HTTP (JSON sau stream) ori MCP (SSE events).

## 4) Tenancy și organizație/agent

* **Precedence config:** `global → org → agent`.
* **Izolare în Qdrant:**

  * **aceeași dimensiune** de embedding (ex. 768): o colecție, filtre pe `org_id`, `agent_id`.
  * **dimensiuni diferite** (ex. o org vrea 1024): colecție separată (vector size e atribut de colecție). ([Qdrant][3])
* **Enforcement la frontieră:** `X-Org-Id`, `X-Agent-Id` în header; serverul validează contra tokenului, nu acceptă override din body.

## 5) Contracte de interfață

### 5.1 HTTP REST

* `POST /api/v1/mem/add`
  Body:

  ```json
  {
    "user_id": "nalyk",
    "messages": [{"role":"user","content":"Nu notificări după 22:00."}],
    "scope": "prefs",
    "tags": ["quiet-hours"],
    "idempotency_key": "sha256(org|agent|user|text)"
  }
  ```

  Headers: `Authorization: Bearer <...>`, `X-Org-Id`, `X-Agent-Id`.

* `GET /api/v1/mem/search?q=notificari&user_id=nalyk&k=6&scope=prefs`
  Răspuns:

  ```json
  {
    "hits":[
      {"id":"...", "score":0.83, "text":"...", "payload":{"org_id":"...","agent_id":"...","scope":"prefs","tags":["quiet-hours"]}}
    ]
  }
  ```

### 5.2 HTTP streaming

* **SSE:** `GET /api/v1/mem/search/stream?...` cu `Content-Type: text/event-stream`; heartbeat `: ping\n\n` la 15–30 s pentru proxy-uri.
* **NDJSON:** `GET /api/v1/mem/search/ndjson?...` cu `application/x-ndjson`:

  ```
  {"type":"hit","score":0.83,"memory":{...}}
  {"type":"hit","score":0.77,"memory":{...}}
  {"type":"done"}
  ```

### 5.3 MCP (SSE)

Conform spec MCP, definești tools: ([Model Context Protocol][5])

* `add_memories(text: string, user_id: string, org_id: string, agent_id: string, scope?: "prefs"|"facts"|"persona"|"constraints", tags?: string[]) -> {items:[{id,...}]}`
* `search_memory(query: string, user_id: string, org_id: string, agent_id: string, k?: number, scope?: string, tags?: string[]) -> {hits:[...]}`
* `update_memory(id: string, patch: object) -> {ok:true}`
* `delete_memory(id: string) -> {ok:true}`

## 6) Modele de date (Qdrant)

**Colecție:** metrică `cosine`, `vectors.size = 768` pentru EmbeddingGemma (asigurat by design). ([Hugging Face][2])

**Payload per item:**

```json
{
  "org_id": "org-123",
  "agent_id": "agent-7",
  "user_id": "nalyk",
  "scope": "prefs",
  "tags": ["quiet-hours","caffeine"],
  "text": "Nu notificări după 22:00.",
  "source": "telegram",
  "ttl_days": 365,
  "created_at": "2025-09-18T15:00:00Z",
  "updated_at": "2025-09-18T15:00:00Z",
  "deleted": false
}
```

**Index HNSW:** `m` și `ef_construct` configurabile; suport **on\_disk** pentru HNSW și vectors la nevoie (low RAM). ([Qdrant][6])

## 7) Configurare și fișiere

### 7.1 TEI + EmbeddingGemma (Docker)

```bash
docker run -d --name tei-embed \
  -p 3000:80 \
  -e HUGGING_FACE_HUB_TOKEN=<HF_TOKEN> \
  ghcr.io/huggingface/text-embeddings-inference:cpu-1.6 \
  --model-id google/embeddinggemma-300m
```

TEI este motorul oficial pentru servirea embeddings cu performanță ridicată; deployment prin container e modul recomandat. ([Hugging Face][7])

### 7.2 Qdrant (Docker Compose)

```yaml
# qdrant.compose.yaml
version: "3.8"
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333","6334:6334"]
    environment:
      - QDRANT__STORAGE__ON_DISK_PAYLOAD=true
    volumes:
      - qdrant_data:/qdrant/storage
volumes:
  qdrant_data:
```

Qdrant combină index vectorial și indexuri pentru payload; parametrii indexului sunt la nivel de colecție. ([Qdrant][3])

### 7.3 Memory core (Python) — config exemplu

```python
# config.py (schematic)
CONFIG = {
  "llm": {
    "provider": "openrouter",
    "config": {
      "api_key": "<OPENROUTER_API_KEY>",
      "openrouter_base_url": "https://openrouter.ai/api/v1",
      "model": "openrouter/auto"  # sau un model free explicit
    }
  },
  "embedder": {
    "provider": "huggingface",
    "config": {
      "huggingface_base_url": "http://tei-embed:80/v1",
      "model": "google/embeddinggemma-300m",
      "embedding_dims": 768
    }
  },
  "vector_store": {
    "provider": "qdrant",
    "config": {"host": "qdrant", "port": 6333, "collection_name": "mem0_main"}
  }
}
```

OpenRouter oferă endpoint OpenAI-compat cu schemă aproape identică, deci integrarea e directă. ([OpenRouter][1])

### 7.4 Nginx (SSE sigur)

```nginx
server {
  listen 443 ssl http2;
  server_name mem.yoda.digital;

  # certs ...

  location /api/ {
    proxy_pass http://http-gw:8080/;
    proxy_set_header Host $host;
    proxy_read_timeout 3600;
  }

  # MCP SSE proxied
  location /mcp/sse {
    proxy_pass http://mcp-gw:8050/sse;
    proxy_set_header Host $host;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_read_timeout 3600;
    add_header X-Accel-Buffering no;
  }
}
```

## 8) Tuning de performanță

* **Qdrant HNSW:** pornește cu `m:16–32`, `ef_construct:128–512`, `ef (search):64–128`; activează `on_disk` când RAM e limitat. Precizia crește cu m/ef, dar și latența. ([Qdrant][6])
* **TEI CPU:** batch 16–32 pentru ingest; containerul TEI este modul suportat oficial și simplu de ridicat. ([Hugging Face][7])
* **OpenRouter:** folosește `openrouter/auto` pentru fallback automat și economie; schema e compatibilă OpenAI. ([OpenRouter][8])

## 9) Securitate și conformitate

* **Auth:** Bearer tokens; `org_id` derivat din token și verificat la fiecare request.
* **Tenancy enforcement:** filtre hard pe `org_id`, `agent_id` în toate interogările Qdrant.
* **Transport:** TLS end-to-end; rate-limit pe IP și pe tenant.
* **Privacy:** TTL pe `scope`/`tags`; endpoint administrativ pentru export/erase pe user.

## 10) Observabilitate

* **Metrics Prometheus:**

  * `mem_add_latency_ms`, `mem_search_latency_ms`, `qdrant_hits`, `qdrant_points_total`, `tei_requests_total`, `openrouter_requests_total`, `mcp_active_clients`
* **Logs JSON:** include `org_id`, `agent_id`, `user_id`, `trace_id`, `top_k_scores`.
* **Tracing:** corelații HTTP/MCP → TEI → Qdrant → OpenRouter.

## 11) Scalare și capacitate

* **Vertical:** măriți vCPU/RAM; activați `on_disk` în Qdrant pentru volum mare. ([Qdrant][6])
* **Orizontal:** shard pe colecții per org când embedding dims rămâne 768; izolare totală când diferă.
* **Caching:** cache scurt al rezultatelor „search” pe interogări frecvente.

## 12) Migrare și compatibilitate embedding

* **MRL:** EmbeddingGemma permite truncare 768→512/256/128; dacă schimbați dimensiunea, creați **colecție nouă** cu vector size potrivit, apoi re-ingestați sau re-indexați incremental. ([Hugging Face][2])

## 13) Testare

* **Unitare:** parsare config, header tenancy, idempotency `add`.
* **Integrare:** TEI health, Qdrant collection create/insert/search, OpenRouter fallback.
* **Load (VPS 2 vCPU/4 GB):**

  * ingest batch 32, min. 50 iteme/s țintă
  * search p95 ≤ 150 ms pentru ≤ 200k memorii, `ef=64–128`
* **Chaos:** latență OpenRouter, restart TEI (cold start sub 30 s). ([Hugging Face][7])

## 14) Runbook

* **Incident: spike latență search**

  * verifică `ef` curent; coboară temporar la 64
  * activează/confirmă `on_disk` HNSW; verifică IOPS stocare ([Qdrant][6])
* **TEI nu răspunde:** health check `/readyz`; dacă 503, redeploy; pre-load model la boot. ([Hugging Face][7])
* **Mismatch dimensiune vector:** confirmă `embedding_dims`, recreează colecția.

## 15) Implementare exemplificată

### 15.1 Compose minimal (TEI + Qdrant + core + gateways)

```yaml
version: "3.8"
services:
  tei-embed:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.6
    command: ["--model-id","google/embeddinggemma-300m"]
    environment: [HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}]
    ports: ["3000:80"]

  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333","6334:6334"]
    environment: [QDRANT__STORAGE__ON_DISK_PAYLOAD=true]
    volumes: ["qdrant_data:/qdrant/storage"]

  memory-core:
    build: ./core
    env_file: .env
    depends_on: [tei-embed,qdrant]

  http-gw:
    build: ./http-gw
    ports: ["8080:8080"]
    depends_on: [memory-core]

  mcp-gw:
    build: ./mcp-gw
    ports: ["8050:8050"]
    depends_on: [memory-core]

volumes:
  qdrant_data:
```

### 15.2 MCP server schematic (Python, SSE)

```python
from mcp.server.fastmcp import FastMCP
from core import MemoryCore  # wrap peste Mem0 config OpenRouter+TEI+Qdrant

app = FastMCP("mem")
core = MemoryCore(...)

@app.tool()
def add_memories(text: str, user_id: str, org_id: str, agent_id: str, scope: str="facts", tags: list[str] = []):
    return core.add(text, user_id, org_id, agent_id, scope, tags)

@app.tool()
def search_memory(query: str, user_id: str, org_id: str, agent_id: str, k: int = 6, scope: str | None = None):
    return core.search(query, user_id, org_id, agent_id, k, scope)

app.run_sse(host="0.0.0.0", port=8050)
```

Conectarea în clienți MCP (ex. Claude Desktop) se face prin „connect local servers” în configul clientului. ([Model Context Protocol][4])

---

## 16) Riscuri majore și mitigare

* **Dependință externă LLM (OpenRouter):** fallback automat + retry; mod „degradat” unde write policy folosește reguli simple când LLM e indisponibil. ([OpenRouter][8])
* **RAM limitat pe VPS:** Qdrant `on_disk`, HNSW m/ef moderate, batch TEI mic. ([Qdrant][6])
* **Migrare dimensiune vector:** colecție nouă + migrare incrementală; nu modifica dimensiunea la colecție existentă. ([Qdrant][3])

---

## 17) Compatibilități cheie (verificate)

* **OpenRouter**: API foarte apropiat de OpenAI, endpoint `/api/v1`, rutare/fallback multi-model. ([OpenRouter][1])
* **TEI**: container oficial; „quick tour” recomandă Docker ca metodă de start; engine conceput pentru producție. ([Hugging Face][7])
* **EmbeddingGemma 300M**: 768 dims, MRL 512/256/128; model card/README. ([Hugging Face][2])
* **Qdrant**: HNSW m/ef + on-disk; payload indexes pentru filtre; parametri la nivel de colecție. ([Qdrant][6])
* **MCP**: standard open; ghid oficial pentru conectarea serverelor locale în clienți (Claude Desktop). ([Model Context Protocol][5])

---

Acesta este documentul 2/3 (Blueprint tehnic). 

[1]: https://openrouter.ai/docs/api-reference/overview?utm_source=chatgpt.com "OpenRouter API Reference | Complete API Documentation"
[2]: https://huggingface.co/google/embeddinggemma-300m?utm_source=chatgpt.com "google/embeddinggemma-300m"
[3]: https://qdrant.tech/documentation/concepts/indexing/?utm_source=chatgpt.com "Indexing"
[4]: https://modelcontextprotocol.io/docs/develop/connect-local-servers?utm_source=chatgpt.com "Connect to local MCP servers"
[5]: https://modelcontextprotocol.io/?utm_source=chatgpt.com "Model Context Protocol"
[6]: https://qdrant.tech/documentation/guides/optimize/?utm_source=chatgpt.com "Optimize Performance"
[7]: https://huggingface.co/docs/text-embeddings-inference/en/quick_tour?utm_source=chatgpt.com "Quick Tour"
[8]: https://openrouter.ai/docs/quickstart?utm_source=chatgpt.com "OpenRouter Quickstart Guide | Developer Documentation"
