**TL;DR:** Mai jos ai PRD-ul complet pentru un „Memory Service” multi-tenant: LLM remote prin **OpenRouter**, embeddings locale prin **EmbeddingGemma** servit cu **Hugging Face TEI**, stocare în **Qdrant**, cu două fețe de integrare la alegere: **MCP (SSE)** și **HTTP (REST + streaming)**. PRD-ul include scop, succes metrics, user stories, cerințe funcționale și nefuncționale, modelul de date, API-urile, securitatea, SLO-urile, observabilitatea, rollout, riscuri și anexă de compatibilitate. Afirmațiile critice sunt documentate din surse oficiale, actuale.

# PRD — „Memory Service” multi-tenant (OpenRouter + EmbeddingGemma/TEI + Qdrant, MCP + HTTP)

## 1) Context și problemă

Agenții tăi AI au nevoie de o memorie persistentă, interogabilă semantic, reutilizabilă între clienți diferiți. Sistemul trebuie să funcționeze „light” pe un VPS, fără GPU, cu generative externalizat și embedding local eficient, plus un protocol de integrare standardizat pentru IDE-uri/agenți (MCP) și un API universal (HTTP) pentru orchestratoare.

## 2) Scop

Livrarea unui serviciu de memorie unificat, multi-tenant, care:

* extrage și normalizează „memorii” cu ajutorul unui LLM remote (OpenRouter, endpoint OpenAI-compat, rutare auto disponibilă),
* encodează local interogări și memorii în vectori cu EmbeddingGemma 300M prin TEI (dimensiune implicită 768, cu opțiuni MRL 512/256/128),
* stochează și regăsește semantic în Qdrant,
* expune aceeași logică prin două interfețe: MCP (SSE) și HTTP (REST + SSE/NDJSON).
  Referințe: OpenRouter quickstart și model routing auto ([OpenRouter][1]), TEI (serving embeddings, air-gapped, Docker) ([Hugging Face][2]), EmbeddingGemma dimensiune 768 și MRL ([Hugging Face][3]), Qdrant colecții cu vector size și index HNSW optimizabil ([Qdrant][4]), MCP spec și ghiduri de conectare în clienți (Claude Desktop etc.) ([Model Context Protocol][5]).

## 3) Obiective măsurabile (Success Metrics)

* Timp mediu de căutare semantică p95 ≤ 150 ms pentru colecții ≤ 200k memorii (VPS 2 vCPU/4 GB), cu ef=64–128. ([Qdrant][6])
* Throughput ingest ≥ 50 memorii/s în batch de 32 pe TEI CPU. ([Hugging Face][2])
* Uptime ≥ 99.5% lunar pentru API și MCP SSE.
* Timp de „cold start” TEI ≤ 30 s după restart. ([Hugging Face][2])
* Zero mismatch de dimensiune vector (validări stricte, 768 by default). ([Hugging Face][3])

## 4) Public țintă și scenarii

* CTO/DevOps: vrea control, cost redus, fără GPU.
* Agenți conversaționali (IDE, chat, bots): memorie preferințe/persoane/fapte.
* Orchestratoare (n8n, interni): scriu/ citesc memorii prin HTTP.
* IDE/CLI (Claude Desktop, Cursor): consumă prin MCP tools. ([Model Context Protocol][7])

## 5) User stories cheie

* Ca agent, înainte de a răspunde, caut top-k memorii relevante în contextul user\_id/org\_id/agent\_id.
* Ca orchestrator, după fiecare interacțiune, adaug memorii candidate cu politică de scriere.
* Ca operator, configurez per organizație și per agent: modele, k, criterii de scriere, retention, colecții.
* Ca auditor, pot filtra și exporta memorii pe org/agent/scope.

## 6) Cerințe funcționale

1. **Extracție/învățare memorie**

   * „Write policy” bazat pe criterii (prefs, facts, constraints).
   * Deduplicare la ingest (hash idempotent pe org/agent/user/text).
   * Actualizare memorie (merge by semantic key).

2. **Căutare semantică**

   * Top-k + filtre obligatorii `org_id`, `agent_id`, opțional `scope`, `tags`.
   * Relevanță = similaritate cosine + time-decay, diversitate opțională.
   * Matryoshka-ready: posibilitatea de a trunchia vectorii la 512/256/128 dacă se schimbă politica per org. ([Hugging Face][3])

3. **Tenancy și configurare stratificată**

   * Precedence: global → org → agent.
   * Parametri override: LLM model (OpenRouter), k, ef, m, write criteria, TTL, scopes weight, collection mapping.

4. **Interfețe**

   * **MCP (SSE)**: tools `add_memories`, `search_memory`, `update_memory`, `delete_memory`. Conform MCP spec (2025-06-18). ([Model Context Protocol][5])
   * **HTTP**: REST (`POST /mem/add`, `GET /mem/search`) și streaming (`/mem/search/stream` SSE sau NDJSON).
   * Compatibilitate clienți MCP (Claude Desktop etc.) prin configurarea local servers. ([Model Context Protocol][7])

5. **Compatibilitate modele**

   * LLM: OpenRouter, inclusiv `openrouter/auto` pentru rutare/fallback. ([OpenRouter][8])
   * Embeddings: TEI cu `google/embeddinggemma-300m` (768 implicit). ([Hugging Face][3])

6. **Stocare**

   * Qdrant colecție cu `size=768`, metric cosine; HNSW `m` și `ef_construction` configurabile; opțiune `on_disk` pentru low-RAM. ([Qdrant][4])

## 7) Cerințe nefuncționale

* **Performanță**: vezi success metrics.
* **Fiabilitate**: retry cu backoff la OpenRouter; reconectare SSE MCP cu heartbeat.
* **Securitate**: Bearer tokens; validare strictă a `org_id` din token; rate-limits pe IP și pe tenant.
* **Legal & Privacy**: PII tagging în payload, TTL configurabile; posibilitate de export/ștergere pe user.
* **Observabilitate**: metrics Prometheus (RPS, p95, fail rate, Qdrant hits/misses), logs structurate cu org/agent/user, trace IDs.
* **Portabilitate**: toate componentele containerizate; fără dependențe GPU.

## 8) Arhitectură (high-level)

* **Core**: Mem0 ca layer logic pentru add/search, cu LLM remote (OpenRouter), embedder TEI, vector store Qdrant. Mem0 suportă configurarea embedders tip Hugging Face și TEI base URL, plus setarea dimensiunii vectorului în config. ([docs.mem0.ai][9])
* **Adaptors**: MCP server (SSE) și HTTP server (REST + SSE/NDJSON) care mapează 1:1 operațiile core.
* **Tenancy**: payload Qdrant obligatoriu cu `org_id`, `agent_id`, `user_id`, `scope`, `tags`. Colecții multiple dacă diferă dimensiunea vectorilor între org-uri.
* **LLM**: OpenRouter API, endpoint OpenAI-compat, rutare automată opțională. ([OpenRouter][10])
* **Embeddings**: TEI container cu `google/embeddinggemma-300m`. ([Hugging Face][2])

## 9) Model de date (rezumat)

* **Memory**

  * `id` (UUID)
  * `vector` (float\[768] implicit)
  * `payload`: `org_id`, `agent_id`, `user_id`, `scope` in {prefs, facts, persona, constraints}, `tags` \[string], `text`, `source`, `created_at`, `updated_at`, `ttl_days`, `version`
* **Search filters**: `must(org_id, agent_id)`; `should(scope weights)`; `must_not(deleted=true)`
* **Index**: HNSW cosine, `m` 16–32, `ef` query 64–128. ([Qdrant][6])

## 10) API (contract minim)

### MCP Tools (SSE)

* `add_memories(text, user_id, org_id, agent_id, scope="facts", tags=[]) -> {items:[{id,...}]}`
* `search_memory(query, user_id, org_id, agent_id, k=6, scope?, tags?) -> {hits:[{id,score,payload,text}]}`
* `update_memory(id, patch) -> {ok:true}`
* `delete_memory(id) -> {ok:true}`
  Conform spec MCP tools, cu schema și metadata declarate. ([Model Context Protocol][11])

### HTTP

* `POST /api/v1/mem/add` body: `{user_id, text|messages[], org_id?, agent_id?, scope?, tags?, idempotency_key?}`
* `GET /api/v1/mem/search?q=...&user_id=...&k=6&scope=...`
* `GET /api/v1/mem/search/stream?...` SSE sau NDJSON; heartbeat la 20 s.
  Headers obligatorii: `Authorization: Bearer`, `X-Org-Id`, `X-Agent-Id` (sau deduse din token).

## 11) Securitate și privacy

* Validare strictă a tenancy: `org_id` este derivat din token; valorile din body sunt ignorate dacă nu corespund.
* Criptare în tranzit (TLS).
* PII tagging și `ttl_days` per scope/tag.
* Export/erase endpoint administrativ per user/tenant.

## 12) Observabilitate

* **Metrics**: `mem_add_latency_ms`, `mem_search_latency_ms`, `qdrant_hits`, `qdrant_vectors`, `tei_req_rate`, `openrouter_req_rate`, `mcp_active_clients`.
* **Logs**: JSON cu `org_id`, `agent_id`, `user_id`, `trace_id`, rezultat top-k, scoruri.
* **Tracing**: corelate request MCP/HTTP → TEI → Qdrant → OpenRouter.

## 13) SLO & capacitate

* SLO disponibilitate 99.5%/lună.
* RPS target: 50 rps read, 10 rps write pe 2 vCPU/4 GB, fără GPU.
* P95 search ≤ 150 ms; P95 add ≤ 300 ms (include TEI + Qdrant write).
* Scale vertical (vCPU/RAM) și orizontal (sharding pe colecții per org).

## 14) Rollout plan

* Faza 1: PoC intern (HTTP + TEI + Qdrant, OpenRouter `openrouter/auto`). ([OpenRouter][8])
* Faza 2: MCP adaptor, validare în Claude Desktop (local servers). ([Model Context Protocol][7])
* Faza 3: Multi-tenant real, policies per org/agent, audit & export.
* Faza 4: Hardening prod: rate-limit, WAF, backup Qdrant, on-disk index pentru low-RAM. ([Qdrant][6])

## 15) Riscuri și mitigări

* **Mismatch dimensiune vector** la schimbarea embedderului: validări stricte; colecție nouă dacă dimensiunea diferă. ([Hugging Face][3])
* **Latență LLM remote**: caching scurt al extragerii, batching add, retry pe erori; auto-router pentru disponibilitate. ([OpenRouter][8])
* **SSE timeouts** în fața proxy-urilor: heartbeat la 15–30 s; `proxy_read_timeout` adecvat.
* **TEI cold start**: preload la boot; readiness probe. ([Hugging Face][2])

## 16) Ne-în-scop (Out of scope)

* Fine-tuning modele; sync bidirecțional cu CRM; UI final pentru end-users (doar endpoints).

## 17) Alternativa respinsă

* LLM local 7B+ pe CPU: cost de resurse prea mare pentru VPS mic.
* Chroma/pgvector în loc de Qdrant: valid, dar Qdrant oferă HNSW on-disk simplu și tuning clar pentru low-RAM. ([Qdrant][6])

## 18) Anexă: Compatibilitate și conformitate

* **OpenRouter**: API similar OpenAI, endpoint `/api/v1`, suport rutare automată. ([OpenRouter][10])
* **TEI**: suportă deploy air-gapped și cele mai populare modele de embeddings. ([Hugging Face][12])
* **EmbeddingGemma**: 300M param, vector 768, MRL pentru 512/256/128. ([Hugging Face][13])
* **Qdrant**: vector size per colecție, HNSW, opțiuni on-disk pentru low-RAM. ([Qdrant][4])
* **MCP**: tools, spec 2025-06-18, clienți cunoscuți (Claude Desktop etc.). ([Model Context Protocol][11])
* **Mem0**: configurabil pentru embedders Hugging Face și TEI base URL; necesită LLM, dar e agnostic de provider la nivel de config. ([docs.mem0.ai][9])

—
Acesta este documentul 1/3.

[1]: https://openrouter.ai/docs/quickstart?utm_source=chatgpt.com "OpenRouter Quickstart Guide | Developer Documentation"
[2]: https://huggingface.co/docs/text-embeddings-inference/en/index?utm_source=chatgpt.com "Text Embeddings Inference"
[3]: https://huggingface.co/google/embeddinggemma-300m?utm_source=chatgpt.com "google/embeddinggemma-300m"
[4]: https://qdrant.tech/documentation/concepts/collections/?utm_source=chatgpt.com "Collections"
[5]: https://modelcontextprotocol.io/specification/2025-06-18?utm_source=chatgpt.com "Specification"
[6]: https://qdrant.tech/documentation/guides/optimize/?utm_source=chatgpt.com "Optimize Performance"
[7]: https://modelcontextprotocol.io/docs/develop/connect-local-servers?utm_source=chatgpt.com "Connect to local MCP servers"
[8]: https://openrouter.ai/docs/features/model-routing?utm_source=chatgpt.com "Model Routing | Dynamic AI Model Selection and Fallback"
[9]: https://docs.mem0.ai/components/embedders/models/huggingface?utm_source=chatgpt.com "Hugging Face"
[10]: https://openrouter.ai/docs/api-reference/overview?utm_source=chatgpt.com "OpenRouter API Reference | Complete API Documentation"
[11]: https://modelcontextprotocol.io/docs/concepts/tools?utm_source=chatgpt.com "Tools"
[12]: https://huggingface.co/docs/text-embeddings-inference/en/quick_tour?utm_source=chatgpt.com "Quick Tour"
[13]: https://huggingface.co/blog/embeddinggemma?utm_source=chatgpt.com "EmbeddingGemma, Google's new efficient embedding model"
