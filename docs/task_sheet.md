**TL;DR:** mai jos este **Documentul de specificații tehnice / Task Sheet** pentru serviciul de memorie: LLM generativ prin **OpenRouter** (remote), embeddings locale cu **EmbeddingGemma 300M** servit prin **Hugging Face TEI**, stocare în **Qdrant**, interfețe **HTTP (REST + SSE/NDJSON)** și **MCP (SSE)**, configurări per organizație și per agent. Specificațiile sunt validate pe documentațiile oficiale: OpenRouter API compatibil cu OpenAI-style, TEI ca engine de producție pentru embeddings, EmbeddingGemma (vector 768) pe Hugging Face, Qdrant cu vector size per colecție și HNSW on-disk, MCP ca standard pentru tool-uri și servere locale. ([OpenRouter][1])

---

# Document de specificații tehnice / Task Sheet

**Proiect:** Memory Service (OpenRouter + EmbeddingGemma/TEI + Qdrant; MCP + HTTP)
**Dată:** 18 septembrie 2025
**Mediu țintă:** VPS DigitalOcean (CPU-only), Nginx în față pentru TLS și timeout-uri SSE

## 1) Scope, livrabile, definiții

* **Scope:** serviciu multi-tenant de memorii pentru agenți/IDE/bots, cu scriere, căutare semantică, actualizare și ștergere, plus politici per org/agent.
* **Livrabile:**

  1. Serviciu **core** (Python) bazat pe Mem0, configurat cu OpenRouter (LLM), TEI (Embeddings), Qdrant (Vector DB).
  2. **Gateway HTTP** (FastAPI) cu REST + SSE/NDJSON.
  3. **Gateway MCP** (SSE) cu tools: `add_memories`, `search_memory`, `update_memory`, `delete_memory`.
  4. **Infra**: Docker Compose, Nginx, scripts de bootstrap colecții Qdrant.
  5. Observabilitate: Prometheus metrics, loguri structurate, health endpoints.
  6. Securitate: Bearer tokens, enforcement tenancy (org/agent), rate limits.
* **Out of scope:** UI final pentru end-users, fine-tuning modele.

## 2) Arhitectură și compatibilități verificate

* **LLM generativ (remote):** OpenRouter, schema foarte apropiată de OpenAI Chat API, endpoint `/api/v1`, rutare/fallback multi-model. ([OpenRouter][1])
* **Embeddings (local):** Text Embeddings Inference (TEI), engine de producție pentru servirea modelelor de embedding. ([Hugging Face][2])
* **Model embedding:** `google/embeddinggemma-300m` pe Hugging Face, 300M, multilingv, vector **768**; acces cu acceptarea licenței HF. ([Hugging Face][3])
* **Vector DB:** Qdrant, vector size per colecție, metric cosine, HNSW; suport on-disk pentru index/vectors în medii cu RAM limitat. ([Qdrant][4])
* **MCP:** standard deschis pentru conectarea clienților (Claude Desktop etc.) la servere locale; ghid oficial pentru „connect local servers.” ([Anthropic][5])
* **Mem0 + TEI + Qdrant:** mem0 documentează embedder „Hugging Face” cu TEI și driver Qdrant. ([docs.mem0.ai][6])

## 3) API design

### 3.1 HTTP REST

* **Auth:** `Authorization: Bearer <token>`, `X-Org-Id`, `X-Agent-Id` (sau org/agent derivat din token).
* **Endpoints:**

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

    Return:

    ```json
    {"items":[{"id":"uuid","payload":{"scope":"prefs","tags":["quiet-hours"]}}]}
    ```
  * `GET /api/v1/mem/search?q=notificari&user_id=nalyk&k=6&scope=prefs`
    Return:

    ```json
    {
      "hits":[
        {"id":"...", "score":0.83, "text":"...", 
         "payload":{"org_id":"...","agent_id":"...","scope":"prefs","tags":["quiet-hours"]}}
      ]
    }
    ```
  * `PATCH /api/v1/mem/{id}` body: `{ "text?": "...", "tags?": [], "scope?": "...", "ttl_days?" : 180 }`
  * `DELETE /api/v1/mem/{id}` → `{ "ok": true }`

### 3.2 HTTP streaming

* **SSE:** `GET /api/v1/mem/search/stream?...` cu `Content-Type: text/event-stream`, heartbeat `: ping\n\n` la 20 s.
* **NDJSON:** `GET /api/v1/mem/search/ndjson?...` cu `application/x-ndjson`, linii `{ "type":"hit" | "done", ... }`.

### 3.3 MCP (SSE)

* **Tools:**

  * `add_memories(text: string, user_id: string, org_id: string, agent_id: string, scope?: "prefs"|"facts"|"persona"|"constraints", tags?: string[]) -> {items:[{id,...}]}`
  * `search_memory(query: string, user_id: string, org_id: string, agent_id: string, k?: number, scope?: string, tags?: string[]) -> {hits:[...]}`
  * `update_memory(id: string, patch: object) -> {ok:true}`
  * `delete_memory(id: string) -> {ok:true}`
* **Compat:** conectare în Claude Desktop prin „connect local MCP servers.” ([Model Context Protocol][7])

## 4) Model de date (Qdrant)

* **Colecție:** `vectors.size = 768`, `distance = Cosine`. ([Qdrant][4])
* **Payload per item:**

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
* **Index:** HNSW `m: 16–32`, `ef_construct: 128–512`; la query `ef: 64–128`. **On-disk** pentru vectori și HNSW în medii low-RAM. ([Qdrant][8])

## 5) Configurații și environment

### 5.1 TEI + EmbeddingGemma

* **Prerechizite:** acceptarea licenței Gemma pe HF și folosirea `HF_TOKEN`. ([Google AI for Developers][9])
* **Pornire CPU:**

  ```bash
  docker run -d --name tei-embed \
    -p 3000:80 \
    -e HUGGING_FACE_HUB_TOKEN=$HF_TOKEN \
    ghcr.io/huggingface/text-embeddings-inference:cpu-1.6 \
    --model-id google/embeddinggemma-300m
  ```

  TEI este engine-ul recomandat pentru servirea embeddings în producție. ([Hugging Face][2])

### 5.2 Qdrant

* **Compose minimal:**

  ```yaml
  services:
    qdrant:
      image: qdrant/qdrant:latest
      ports: ["6333:6333","6334:6334"]
      environment:
        - QDRANT__STORAGE__ON_DISK_PAYLOAD=true
      volumes: ["qdrant_data:/qdrant/storage"]
  volumes: { qdrant_data: {} }
  ```

  Vector size este proprietate a colecției; se validează la creare. ([Qdrant][4])

### 5.3 Core (Mem0) — config schematic

```python
CONFIG = {
  "llm": {
    "provider": "openrouter",
    "config": {
      "api_key": "<OPENROUTER_API_KEY>",
      "openrouter_base_url": "https://openrouter.ai/api/v1",
      "model": "openrouter/auto"
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

OpenRouter expune un API foarte apropiat de OpenAI, cu endpoint `/api/v1`. ([OpenRouter][1])
Mem0 documentează explicit embedderul Hugging Face/TEI și driverul Qdrant. ([docs.mem0.ai][6])

### 5.4 Nginx (SSE sigur)

```nginx
location /api/ {
  proxy_pass http://http-gw:8080/;
  proxy_read_timeout 3600;
  add_header X-Accel-Buffering no;
}
location /mcp/sse {
  proxy_pass http://mcp-gw:8050/sse;
  proxy_http_version 1.1;
  proxy_set_header Connection "";
  proxy_read_timeout 3600;
  add_header X-Accel-Buffering no;
}
```

## 6) Tenancy și policy layering

* **Precedence:** `global → org → agent`.
* **Izolare:**

  * aceeași dimensiune (768): o colecție, filtre pe `org_id`, `agent_id`.
  * dimensiune diferită (ex. alt embedder): colecție separată.
* **Headers obligatorii:** `X-Org-Id`, `X-Agent-Id` (sau deduse din token).
* **Validare:** `org_id` din token prevalează; body ignorat dacă nu corespunde.

## 7) Performance budgets

* **Search p95:** ≤ 150 ms pentru ≤ 200k memorii, `ef: 64–128`, VPS 2 vCPU/4–8 GB.
* **Ingest:** ≥ 50 iteme/s în batch 16–32 (TEI CPU). TEI e proiectat pentru performanță ridicată la embeddings. ([Hugging Face][2])
* **Cold start TEI:** ≤ 30 s după restart, în funcție de disc/rețea. ([Hugging Face][2])

## 8) Securitate

* **Auth:** Bearer JWT cu `org_id`, `agent_id` claims.
* **Rate limiting:** per IP și per tenant.
* **Transport:** TLS end-to-end; HSTS; headers securitate.
* **Privacy:** `ttl_days` per scope/tag; endpoint administrativ pentru export/erase pe user.

## 9) Observabilitate

* **Metrics Prometheus:**
  `mem_add_latency_ms`, `mem_search_latency_ms`, `qdrant_points_total`, `qdrant_search_latency_ms`, `tei_requests_total`, `openrouter_requests_total`, `mcp_active_clients`.
* **Logs JSON:** `org_id`, `agent_id`, `user_id`, `trace_id`, top-k scores, ef, m.
* **Health:** `/healthz` gateway, `/readyz` TEI, `/collections` Qdrant.

## 10) Teste și acceptanță

### 10.1 Unit/integration

* **Config parsing** cu precedence global→org→agent (DoD: override corect la toate cheile).
* **Qdrant create/insert/search** cu `size=768` (DoD: reject mismatch).
* **TEI embedding** pentru text RO/RU; numeric vector de 768 (DoD: non-zero norm).
* **HTTP REST**: happy path și erori (401/403, 400 invalid scope).
* **MCP tools**: tool calls și streaming events.

### 10.2 Load & reliability

* **Ingest:** 5k inserturi batch 32; fail rate < 0.5%.
* **Search:** 10 rps pe 50k memorii; p95 ≤ 150 ms.
* **Resilience:** restart TEI în timp ce rulează căutări; reconectare SSE la 2 s.

### 10.3 Acceptance Criteria

* API REST și MCP oferă rezultate identice la aceleași filtre.
* Tenancy enforcement: niciun hit cross-org la teste negative.
* Matryoshka ready: suport truncare vector la 512/256 pentru org-uri opt-in (migrare cu colecție nouă).

## 11) Plan de implementare (task breakdown)

### Săptămâna 1: fundație și POC

* \[BE] Bootstrap repo mono (core, http-gw, mcp-gw, infra).
* \[Infra] Compose TEI + Qdrant; health checks.
* \[BE] Integrare OpenRouter în Mem0 (config minimal).
* \[BE] Embeddings via TEI în Mem0 (HF provider).
* \[BE] Qdrant driver în Mem0, colecție `mem0_main (size=768)`.
* \[QA] Teste integrare minime (create, insert, search).
  **Gate:** POC end-to-end funcțional.

### Săptămâna 2: gateway-uri și tenancy

* \[BE] HTTP REST endpoints + SSE/NDJSON streaming.
* \[BE] MCP server (SSE) cu tools `add/search/update/delete`.
* \[Sec] JWT auth + enforcement `org_id`/`agent_id`.
* \[BE] Config precedence global→org→agent.
* \[QA] Teste auth negative; cross-org isolation.

### Săptămâna 3: performanță, observabilitate

* \[Ops] Prometheus metrics + loguri structurate.
* \[BE] HNSW tuning m/ef + on-disk config Qdrant (low-RAM). ([Qdrant][8])
* \[QA] Benchmarks (budgets din secțiunea 7).
* \[Ops] Nginx în față, TLS, keep-alive, heartbeat SSE.

### Săptămâna 4: hardening, migrare, livrare

* \[BE] Endpoints admin: export/erase pe user/tenant.
* \[Ops] Backup/restore Qdrant; runbook incidente.
* \[QA] Chaos: OpenRouter latency, TEI restarts, Qdrant on-disk.
* \[Docs] OpenAPI, MCP schema, playbook de integrare pentru agenți.

## 12) Riscuri & mitigări

* **Disponibilitate LLM remote:** retry + backoff; „degraded write policy” când LLM indisponibil. ([OpenRouter][1])
* **RAM limitat:** activați on-disk pentru vectors + HNSW, parametri ef/m moderat. ([Qdrant][8])
* **Migrare dimensiune:** colecție nouă cu vector size diferit; migrare incrementală.
* **Licență Gemma:** necesită accept pe HF; automatizați verificarea la boot. ([Google AI for Developers][9])

## 13) Checklists

### Dev Ready

* [ ] Config global→org→agent încărcat și validat
* [ ] TEI `/v1/embeddings` returnează vector 768
* [ ] Qdrant collection `size=768` creată
* [ ] OpenRouter key valid, model setat
* [ ] Teste unit + integrare verzi

### Ops Ready

* [ ] TLS on
* [ ] Nginx SSE heartbeat 20 s
* [ ] Prometheus scrape endpoints
* [ ] Backup/restore Qdrant testat
* [ ] Rate limit per IP/tenant

## 14) Runbook incidente

* **Spike latență search:** reduce temporar `ef` la 64, verifică IOPS; confirmă că index/vectors sunt pe disk dacă RAM e la limită. ([Qdrant][8])
* **TEI 5xx:** verifică `/readyz`; redeploy; warm-up la boot (prim request). ([Hugging Face][2])
* **OpenRouter 5xx/timeouts:** fallback auto-router sau model explicit alternativ; retry cu backoff. ([OpenRouter][1])
* **Mismatch vector size:** blochează writes, alertează; creează colecție corectă și re-ingest.

## 15) Extensii viitoare

* Reranking local (e.g., BGE-reranker) via TEI dacă este suportat.
* Sparse + dense hibrid în Qdrant; payload index on-disk pentru filtre masive. ([Qdrant][10])
* Org-level collections sharding pentru trafic ridicat.

---

### Note de validare (surse)

* **OpenRouter API** foarte apropiat de OpenAI Chat API; endpoint `/api/v1`, multi-model routing. ([OpenRouter][1])
* **TEI** ca engine de producție pentru embedding, documentație oficială + ghid „engines/tei.” ([Hugging Face][2])
* **EmbeddingGemma** pe Hugging Face, 300M, vector 768, acces cu accept licență. ([Hugging Face][3])
* **Qdrant**: vector size per colecție, HNSW; mod **on-disk** pentru index+vectors reduce RAM. ([Qdrant][4])
* **MCP**: standard deschis; conectare la servere locale în Claude Desktop. ([Model Context Protocol][11])

Acesta a fost documentul 3/3.

[1]: https://openrouter.ai/docs/api-reference/overview?utm_source=chatgpt.com "OpenRouter API Reference | Complete API Documentation"
[2]: https://huggingface.co/docs/text-embeddings-inference/en/index?utm_source=chatgpt.com "Text Embeddings Inference"
[3]: https://huggingface.co/google/embeddinggemma-300m?utm_source=chatgpt.com "google/embeddinggemma-300m"
[4]: https://qdrant.tech/documentation/concepts/collections/?utm_source=chatgpt.com "Collections"
[5]: https://www.anthropic.com/news/model-context-protocol?utm_source=chatgpt.com "Introducing the Model Context Protocol"
[6]: https://docs.mem0.ai/components/embedders/models/huggingface?utm_source=chatgpt.com "Hugging Face"
[7]: https://modelcontextprotocol.io/docs/develop/connect-local-servers?utm_source=chatgpt.com "Connect to local MCP servers"
[8]: https://qdrant.tech/documentation/guides/optimize/?utm_source=chatgpt.com "Optimize Performance"
[9]: https://ai.google.dev/gemma/docs/embeddinggemma/fine-tuning-embeddinggemma-with-sentence-transformers?utm_source=chatgpt.com "Fine-tune EmbeddingGemma | Google AI for Developers"
[10]: https://qdrant.tech/documentation/concepts/indexing/?utm_source=chatgpt.com "Indexing"
[11]: https://modelcontextprotocol.io/?utm_source=chatgpt.com "Model Context Protocol"
