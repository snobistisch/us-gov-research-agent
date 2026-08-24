# Architecture Decision: SEC and U.S. Federal Research Agent

Status: **Accepted and implemented after Phase 1 review**
Research verified: **2026-08-24**
Phase 1 scope was research and design only; application code was added only after review.

## 1. Decision summary

Build a small Python 3.12 command-line application around one Pydantic AI agent and seven read-only, typed tools—one for each official data source. The agent selects tools, receives normalized evidence records, and writes a cited answer. It is not a multi-agent system.

Recommended stack:

- **Agent loop:** `pydantic-ai-slim`, using ordinary function tools and `UsageLimits`.
- **Default model:** `openai-responses:gpt-5.6-luna`, with low reasoning effort initially. It is the current OpenAI model intended for cost-sensitive workloads and supports function calling and structured outputs.
- **Provider portability:** one setting, `LLM_MODEL`, uses Pydantic AI's `provider:model` form, for example `openai-responses:gpt-5.6-luna`. A user can change that value to a supported provider/model and supply that provider's own key; tool and orchestration code does not change.
- **HTTP:** one shared `httpx.AsyncClient`, source-specific rate policies, retries, timeouts, and a per-query HTTP budget.
- **Cache:** a local SQLite-backed HTTP/document cache in the operating system's user cache directory, never inside the repository by default.
- **Evidence contract:** every tool returns the same bounded `EvidenceRecord` shape with a canonical primary-source URL. The final answer cites evidence IDs such as `[S1]`, which are validated before display.
- **Default ceilings:** 8 successful tool calls, 6 model requests, 20 outbound government HTTP requests, 3 pages per tool call, and a bounded evidence payload per query.

This is the smallest design that supplies typed tool schemas, multi-step tool use, provider swapping, deterministic tests, and hard usage limits without introducing graph or multi-agent infrastructure.

## 2. Data-source evaluation

### At-a-glance matrix

| Source | Base URL and useful surfaces | Authentication | Published rate limit | Response formats | Best use |
|---|---|---|---|---|---|
| SEC EDGAR | `https://data.sec.gov`; filings at `https://www.sec.gov/Archives/edgar/data/`; search UI backend at `https://efts.sec.gov/LATEST/search-index` | Keyless. All automated requests must send a descriptive `User-Agent` naming the requester and contact email. | SEC-wide maximum 10 requests/second; use an internal 5 requests/second cap. | Retrieval APIs and full-text results: JSON. Filing documents: HTML, text, XML, inline XBRL, and sometimes PDF. | Company filing history, latest filings, filing text, comparable XBRL facts, and filing discovery. |
| Congress.gov API v3 | `https://api.congress.gov/v3` | Free `api.data.gov` key | 5,000 requests/hour | JSON or XML; request JSON explicitly. | Bills, amendments, actions, summaries, members, committees, nominations, treaties, and House roll-call votes. |
| Federal Register API v1 | `https://www.federalregister.gov/api/v1` | Keyless | No numeric public limit found in the official documentation; throttle politely. | JSON; search/export also supports CSV. Documents link to official GPO PDFs. | Final/proposed rules, notices, presidential documents, executive orders, agencies, CFR citations, and public-inspection metadata. |
| USAspending API v2 | `https://api.usaspending.gov/api/v2` | Keyless | No numeric public limit is documented. | JSON; bulk-download endpoints produce ZIP/CSV. | Federal awards, contracts, grants, loans, recipients, agencies, accounts, obligations, and outlays. |
| Treasury Fiscal Data | `https://api.fiscaldata.treasury.gov/services/api/fiscal_service` | Keyless | No numeric public limit found in the official documentation; throttle politely. | JSON by default; CSV and XML through `format`. | Debt, Treasury statements, receipts/outlays, interest, auctions, exchange rates, and other authoritative fiscal series. |
| Regulations.gov API v4 | `https://api.regulations.gov/v4` | Free `api.data.gov` key in `X-Api-Key` | Documentation defers GET limits to api.data.gov; the platform default is 1,000 requests/hour unless the service/response headers specify otherwise. POST commenting is 50/minute and 500/hour, but POST is out of scope. | JSON:API (`application/vnd.api+json`) | Rulemaking dockets, regulatory documents, supporting material, and public comments. |
| GovInfo API | `https://api.govinfo.gov` | Free `api.data.gov` key | 36,000/hour, 1,200/minute, 40/second for normal keys | JSON discovery/summary; content in HTM, text, PDF, XML, ZIP, MODS, and PREMIS as available. | Official publications across all three branches: bills and laws, Congressional Record, CFR, Federal Register, hearings, reports, court opinions, and authenticated package metadata. |

All seven sources are free. One free `api.data.gov` key can be used with Congress.gov, Regulations.gov, and GovInfo. The LLM is the only expected metered component.

### 2.1 SEC EDGAR

Official retrieval documentation: [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [SEC developer FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions), [SEC rate-control notice](https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits), and [EDGAR Full Text Search FAQ](https://www.sec.gov/edgar/search/efts-faq.html).

#### Supported surfaces

- `GET https://data.sec.gov/submissions/CIK##########.json` returns company metadata and at least one year or 1,000 recent filings, with links to older submission files.
- `GET https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` returns all standardized facts for one company.
- `GET https://data.sec.gov/api/xbrl/companyconcept/{CIK}/{taxonomy}/{tag}.json` returns one concept for one company.
- `GET https://data.sec.gov/api/xbrl/frames/{taxonomy}/{tag}/{unit}/{period}.json` returns the most recently filed comparable fact per reporting entity for a calendar frame.
- `GET https://www.sec.gov/Archives/edgar/data/{cik}/{accession_without_dashes}/{primary_document}` retrieves the actual filing document that the answer should cite.
- `GET https://www.sec.gov/files/company_tickers.json` resolves common tickers and company names to CIKs.
- EDGAR's browser full-text search covers electronically filed material since 2001 and searches filing text plus attachments. Its current UI calls `https://efts.sec.gov/LATEST/search-index`, which was verified live during this research and returns JSON.

#### Important caveats

- The SEC's documented public data host is **`data.sec.gov`**, not `api.sec.gov`. `api.sec.gov` did not resolve during verification and must not be used as a configured base URL.
- The `efts.sec.gov/LATEST/search-index` JSON route is an observable SEC-operated UI backend, but it is not documented as a stable public API contract. Treat it as best-effort discovery: isolate it behind an adapter, test its response shape, cache results, and fall back to submissions metadata plus filing retrieval when it changes.
- `data.sec.gov` does not support browser CORS. That is irrelevant to the CLI but argues against a browser-only client.
- The newer `api.edgarfiling.sec.gov` bearer-token APIs are for filers managing accounts and submitting filings; they are not needed for public research.
- Frames only include standardized, entity-wide facts and align companies to calendar frames approximately. They are useful for comparisons, not a substitute for reading the filing or company-specific extensions.

#### Policy for this application

Require a non-secret `SEC_USER_AGENT` such as `Organization Name monitored@domain.tld`. Refuse SEC requests when it is absent, lacks a descriptive identity and contact email, or uses a placeholder or `noreply` mailbox. Give an actionable but redacted error for an SEC HTTP 403. Use a 5 requests/second token bucket with concurrency 2—comfortably below the SEC's 10 requests/second maximum—and cache immutable accession documents indefinitely.

### 2.2 Congress.gov API

Official documentation: [Congress.gov API OpenAPI UI](https://api.congress.gov/), [Library of Congress API repository](https://github.com/LibraryOfCongress/api.congress.gov), and its [change log](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/ChangeLog.md).

- Base: `https://api.congress.gov/v3`.
- Auth: free `api.data.gov` key, accepted as documented by Congress.gov.
- Limit: 5,000 requests/hour. Results default to 20 and can be raised to 250.
- Format: JSON or XML. A June 2026 change made XML the consistent default, so every request should send `format=json` rather than depend on defaults.
- Best for: bills and bill text links; actions, titles, cosponsors and related bills; amendments; members; committees; nominations; treaties; committee reports/meetings; Congressional Record metadata; and House roll-call vote endpoints.

Vote coverage needs precise wording. The API now has House roll-call endpoints, but it does not expose an equivalent complete Senate vote API. Bill actions can link to chamber vote records. The agent must say “House roll-call data” or follow the official linked Senate record rather than imply uniform chamber coverage.

Internal policy: 1 request/second with a small burst, use returned rate-limit headers when present, and prefer linked bill text or GovInfo's official package content for quotations.

The official bill, member, and House-vote list operations expose pagination and structural filters,
but no server-side free-text query parameter. The adapter must paginate using its own `offset`
values rather than consuming returned `next` URLs, keeping credential handling centralized. It
scans at most 3,000 member or House-vote rows and 1,000 recent bill rows per tool call so the
20-request ceiling remains enforceable. If more pages exist, returned evidence carries a coverage
note; a miss becomes an explicit bounded-coverage error. Exact bill identifiers plus Congress
number and exact member Bioguide IDs bypass list search.

### 2.3 Federal Register API

Official documentation: [Federal Register API v1](https://www.federalregister.gov/developers/documentation/api/v1) and [NARA's API implementation](https://github.com/usnationalarchives/federalregister-api-core).

- Base: `https://www.federalregister.gov/api/v1`.
- Auth: none; the official documentation explicitly says no API key is required.
- Limit: the official documentation does not publish a numeric quota. This document therefore does not claim one.
- Format: JSON endpoints such as `/documents.json`, `/documents/{document_number}.json`, `/agencies.json`, and public-inspection endpoints; CSV is also available for search/export use.
- Best for: keyword and structured search over rules, proposed rules, notices, and presidential documents; executive orders; agency and CFR metadata; comment deadlines; Regulations.gov docket IDs; and convenient HTML/text links.

FederalRegister.gov says its XML rendition is an unofficial informational resource and links each item to the corresponding official GovInfo PDF. For legal-status-sensitive claims, expose both URLs and cite the official GovInfo edition when available.

Internal policy: 2 requests/second, concurrency 2, three retry attempts, and a one-hour search TTL. A specific published document number can be cached long-term.

### 2.4 USAspending.gov API

Official documentation: [USAspending API endpoints](https://api.usaspending.gov/docs/endpoints) and [USAspending API repository](https://github.com/fedspendingtransparency/usaspending-api).

- Base: `https://api.usaspending.gov/api/v2`.
- Auth: none; the endpoint reference says authorization is not currently required.
- Limit: no numeric rate limit is published in the official endpoint documentation. An open issue asking about transient failures reinforces that clients must not infer an unpublished quota.
- Format: JSON for normal GET/POST search endpoints. Bulk download endpoints generate ZIP files containing CSV data.
- Best for: award and transaction search, award details, recipient and agency rollups, contracts, grants, direct payments, loans, federal accounts, geographic spending, obligations, and outlays.

Most useful searches are POST requests with JSON filter bodies; “read-only” here means that those POSTs query data and never mutate it. The tool will allowlist search/read endpoints and must not accept an arbitrary URL or HTTP method.

Internal policy: 1 request/second, concurrency 2, retry transient empty/5xx responses, limit results and pages, and cache normalized request bodies so semantically identical POST searches share cache entries.

### 2.5 Treasury Fiscal Data API

Official documentation: [Treasury Fiscal Data API documentation](https://fiscaldata.treasury.gov/api-documentation/) and the [Debt to the Penny dataset](https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/).

- Base: `https://api.fiscaldata.treasury.gov/services/api/fiscal_service`.
- Auth: none; it is an open GET API with no user account or token.
- Limit: no numeric limit is stated in the official documentation reviewed.
- Format: JSON by default; `format=csv` and `format=xml` are supported.
- Best for: Debt to the Penny, Monthly and Daily Treasury Statements, revenue and outlays, average interest rates, interest expense, Treasury auctions, historical debt, exchange rates, and other Bureau of the Fiscal Service series.

Endpoints are dataset-specific and versioned. The tool should expose an allowlisted dataset identifier rather than letting the model construct paths. It should support the documented `fields`, `filter`, `sort`, `format`, and pagination concepts through typed inputs.

Internal policy: 2 requests/second, cache date-bounded historical queries for seven days or longer, cache “latest” queries for one hour, and preserve Treasury's field names and units in normalized metadata.

### 2.6 Regulations.gov API

Official documentation: [GSA Regulations.gov API](https://open.gsa.gov/api/regulationsgov/) and [api.data.gov rate-limit manual](https://api.data.gov/docs/developer-manual/).

- Base: `https://api.regulations.gov/v4`.
- Auth: a free `api.data.gov` key in the `X-Api-Key` header on every request.
- GET limit: Regulations.gov points to api.data.gov's limits. The platform default is 1,000 requests/hour on a rolling basis, but service-specific limits and response headers take precedence.
- Format: JSON:API. Requests should use `Accept: application/vnd.api+json`; the same media type is required as `Content-Type` for comment POSTs.
- Best for: full-text/filtered searches of documents and comments, docket details, attachments, supporting material, and the linkage among a Federal Register document, docket, and comments.

This research agent is strictly read-only. It will implement only GETs for `/documents`, `/comments`, and `/dockets`. The model will not be given the commenting POST endpoint, submission-key endpoint, or file-upload endpoint.

Internal policy: approximately one request every four seconds (250/hour) by default, well below the platform default; adapt to `X-RateLimit-*` and `Retry-After` headers.

### 2.7 GovInfo API

Official documentation: [GovInfo API feature overview](https://www.govinfo.gov/features/api), [GovInfo interactive API](https://api.govinfo.gov/docs), and [GPO's API repository](https://github.com/usgpo/api).

- Base: `https://api.govinfo.gov`.
- Auth: a free `api.data.gov` key.
- Limits for a normal key: 36,000/hour, 1,200/minute, and 40/second. The API returns rate-limit headers. `DEMO_KEY` is only for exploration and has lower limits.
- Format: JSON for search, collections, published, related, package summaries, and granule summaries. Depending on the package, content is downloadable as HTM/text, PDF, XML, ZIP, MODS, or PREMIS.
- Best for: the official published artifact and metadata for Congressional bills and records, public/private laws, committee reports and hearings, the Federal Register, CFR, U.S. Code, presidential documents, and other publications from all three branches.

The tool should use discovery endpoints to find a package, then return canonical `www.govinfo.gov/app/details/...` links and direct content links. A 503 while generating ZIP or MODS content can include `Retry-After: 30`; this is expected asynchronous generation, not an ordinary permanent failure.

Internal policy: 5 requests/second, concurrency 2, respect all rate headers, and cache package content by package/granule ID plus `lastModified`.

## 3. Agentic workflow options

### Option A — hand-rolled provider SDK loop

Implement the classic loop directly: send prompt and JSON schemas, inspect tool calls, validate arguments, execute functions, append results, and repeat until final text.

Advantages:

- Smallest conceptual and dependency surface for one provider.
- Full visibility into every message and tool decision.
- Easy to add exact custom logging and limits.

Disadvantages:

- Provider APIs differ in tool-call messages, parallel calls, structured output, retries, and usage accounting.
- Typed schemas, validation feedback, test models, model adapters, and cost ceilings become application-owned infrastructure.
- A “single environment variable” provider swap is not realistic without adding and maintaining adapters or a gateway such as LiteLLM.

Conclusion: viable, but deceptively expensive to maintain for this project's portability and validation requirements.

### Option B — Pydantic AI core agent (recommended)

Use one `Agent`, seven typed function tools, and Pydantic models for normalized evidence. Pydantic AI builds JSON schemas from typed signatures/docstrings, validates tool arguments, returns tool results to the model, and supports multiple providers through `provider:model` strings. Its `UsageLimits` covers model requests, tokens, and tool calls; `TestModel`/`FunctionModel` enable tests that make no real model request. Dollar cost is estimated from reported usage, while strict token caps provide the enforceable provider-independent backstop.

Use the slim distribution with only needed provider extras. Relevant documentation: [function tools](https://pydantic.dev/docs/ai/tools-toolsets/tools/), [model providers](https://pydantic.dev/docs/ai/models/overview/), [usage limits](https://pydantic.dev/docs/ai/core-concepts/agent/), [testing](https://pydantic.dev/docs/ai/guides/testing/), and [slim installation](https://pydantic.dev/docs/ai/overview/install/).

Advantages:

- Typed tools and outputs align directly with the Phase 3 acceptance criteria.
- Provider/model swap through `LLM_MODEL=<provider>:<model>`.
- Built-in hard limits and deterministic, zero-cost unit-test models.
- Much less framework machinery than a graph runtime.
- The loop remains inspectable: log model request number, selected tool, validated arguments with credentials redacted, duration, cache hit, evidence IDs, tokens, and estimated cost.

Disadvantages:

- Adds Pydantic AI and provider SDK dependencies.
- Provider portability is not identical model behavior; integration tests are still needed for each advertised provider/model.
- Framework version upgrades can change model profiles or adapter behavior, so dependencies should be constrained and tested.

Conclusion: the leanest option that meets all requirements reliably.

### Option C — LangGraph/LangChain graph runtime

Model the workflow as graph nodes for planning, each source, evidence review, synthesis, and citation checking. LangGraph provides graph state, checkpointing, durable persistence, subgraphs, and prebuilt tool nodes. See its [official overview](https://reference.langchain.com/python/langgraph/overview) and [persistence documentation](https://docs.langchain.com/oss/python/langgraph/persistence).

Advantages:

- Strong fit for long-running, resumable, branching workflows with human approval.
- Explicit state transitions and persistence.
- Easy future extension to complex workflows or multiple actors.

Disadvantages:

- More abstractions, dependencies, state schemas, and debugging surface than this single-run CLI needs.
- Checkpointing and multi-actor features do not improve the core task of calling a few read-only APIs and synthesizing one answer.
- Higher maintenance burden and more framework-specific tests.

Conclusion: reject for v1. Reconsider only if requirements add resumable jobs, durable human-in-the-loop approval, or workflows that cannot fit a bounded single-agent run.

## 4. Recommended workflow

```text
question
   |
   v
single Pydantic AI agent -- chooses one or more typed read-only tools
   |                           |
   |                           v
   |                    source adapter
   |                    rate limit -> cache -> official API
   |                           |
   |                           v
   |                    EvidenceRecord[]
   |                           |
   +---------------------------+
   |
   v
cited synthesis using [S1], [S2], ...
   |
   v
deterministic citation/URL validation
   |
   +-- valid --> rendered answer + Sources
   +-- invalid -> one repair attempt, then explicit incomplete-answer error
```

### 4.1 Tool boundary

Expose exactly these high-level read-only tools to the model:

1. `search_sec_edgar`
2. `search_congress`
3. `search_federal_register`
4. `search_usaspending`
5. `query_treasury_fiscal_data`
6. `search_regulations_gov`
7. `search_govinfo`

Each schema uses typed, bounded fields such as `query`, `operation`, identifiers, date range, form/document type, agency, `limit <= 10`, and `page <= 3`. Models never receive arbitrary URLs, headers, HTTP methods, raw filter languages, file paths, or credentials. An adapter maps the safe schema to allowlisted HTTPS hosts and endpoints.

A tool may perform a small deterministic sequence internally. For example, `search_sec_edgar(company="Tesla", form="10-K", section="risk factors", latest=true)` may resolve Tesla's CIK from the cached SEC ticker map, retrieve submissions, choose the newest 10-K, and fetch the primary filing. Those HTTP requests count against the query's HTTP budget even though the sequence is one model tool call.

### 4.2 Normalized evidence

Every tool returns bounded records shaped conceptually as:

```text
EvidenceRecord
  id: assigned by orchestrator, e.g. S1
  source: sec | congress | federal_register | usaspending | treasury | regulations | govinfo
  title: human-readable primary document title
  canonical_url: public official HTTPS URL used in the final citation
  document_id: accession, bill/package/document/award/docket ID, etc.
  published_at: source date when available
  retrieved_at: UTC timestamp
  excerpt: short relevant text or normalized facts
  fields: source-specific typed metadata, including units
  content_sha256: integrity/cache identity
```

Raw API payloads stay out of the model context unless small and relevant. Adapters strip navigation noise, normalize dates and money without losing raw values/units, and return a maximum of 10 records and a bounded excerpt size. For long filings, extract the requested item/section deterministically before asking the model to synthesize it.

### 4.3 Grounding and citations

- The system prompt says that the evidence is authoritative and that unsupported claims must be omitted or marked as uncertainty.
- Every material factual claim must end with one or more evidence IDs, for example `[S2]`.
- The renderer replaces evidence IDs with numbered Markdown links to `canonical_url` and emits a Sources list.
- A deterministic validator rejects unknown IDs, non-HTTPS links, and hosts outside the official allowlist.
- A citation-coverage check flags factual sentences/paragraphs without an evidence marker. The model gets one bounded repair turn with the same evidence; it may not call more tools during repair.
- Search result pages are discovery citations only. Whenever possible, cite the actual SEC filing, bill text, Federal Register/GovInfo document, award page, Treasury dataset, docket document, or GovInfo package.
- The answer records retrieval date and distinguishes `filed`, `published`, `effective`, `award`, and `last updated` dates rather than collapsing them into “date.”

This provides grounded citations but does not prove that every inference is correct. Tests must cover claim-to-source linkage, and the CLI should state when data is incomplete, delayed, or coverage-limited.

## 5. Model and provider choice

### Default: `openai-responses:gpt-5.6-luna`

Official OpenAI documentation currently describes GPT-5.6 Luna as optimized for cost-sensitive, high-volume workloads. It supports function calling and structured outputs, has a 1.05-million-token context window, and is priced at **$0.20 per million input tokens, $0.02 per million cached input tokens, and $1.20 per million output tokens**. See the [OpenAI model catalog](https://developers.openai.com/api/docs/models) and [model comparison](https://developers.openai.com/api/docs/models/compare).

Why Luna instead of the absolute strongest model:

- The difficult retrieval work is constrained by typed tools and deterministic adapters; the model mainly routes, selects, and synthesizes.
- Its function-calling support satisfies the orchestration need at a fraction of Terra/Sol pricing.
- The current official guidance places Luna in the cost-sensitive role. Older GPT-5 mini/nano models remain listed but are previous-generation choices, so they should not be the default for a new project.

Reliability policy: maintain a small evaluation set spanning all sources and the acceptance question. If Luna misses the required tool or produces citation failures above the agreed threshold, change the default to `openai-responses:gpt-5.6-terra` or use an opt-in `--quality` profile. This should be an evidence-based test decision, not an assumption that a larger model is always needed.

### Provider swapping

```text
LLM_MODEL=openai-responses:gpt-5.6-luna
```

Changing only `LLM_MODEL` selects another Pydantic AI-supported provider/model, while that provider's conventional API-key variable supplies authentication. Examples and tests must never promise identical behavior across providers; CI can run adapter/unit tests without any LLM key, and optional live tests can be explicitly enabled by the user.

### Rough LLM cost per query

Working estimate for a normal research question:

- 10,000–30,000 cumulative uncached input tokens across several model turns, after evidence truncation.
- 2,000–6,000 output/reasoning tokens.
- At Luna's current prices: approximately **$0.004–$0.013 per query**.

A deliberately conservative bounded example of 50,000 input plus 8,000 output tokens costs about **$0.0196**. Government API calls are free. Actual cost varies with tool-loop length, document size, reasoning effort, provider accounting, and prompt caching; the CLI should report provider token usage and estimated cost when available rather than present this estimate as a guarantee.

## 6. Reliability and cost controls

### 6.1 Two-layer cache

Use an OS-appropriate cache directory via `platformdirs`, for example `~/.cache/us-gov-research-agent/` on many Unix systems. Never put cache data, fetched filings, or local `.env` files in tracked repository paths.

1. **HTTP cache:** key on source, method, canonical URL, sorted query parameters, canonical JSON body, and content-negotiation headers. Exclude/redact API keys, `Authorization`, `X-Api-Key`, and SEC contact values from keys and logs.
2. **Document/evidence cache:** store decompressed/extracted primary documents and normalized `EvidenceRecord`s by SHA-256. SQLite stores metadata; large bodies may be gzip-compressed blobs addressed by hash.

Honor `ETag`, `Last-Modified`, `Cache-Control`, and conditional requests where supplied. Provide `--refresh`, an LRU size ceiling (default 1 GiB), and a `cache clear` command. Do not cache authentication failures. Cache 404s for at most five minutes.

Suggested TTLs:

| Content | TTL |
|---|---|
| SEC filing by accession and document name | Indefinite; immutable identity |
| SEC submissions/company facts | 5 minutes |
| SEC frames | 1 hour |
| SEC/Federal Register/GovInfo search result | 15–60 minutes |
| Published Federal Register document or final chamber vote | 30 days, then conditional revalidation |
| Congress bill/member detail | 6 hours; shorter for active bills if needed |
| USAspending search/detail | 6–24 hours |
| Treasury “latest” query | 1 hour |
| Treasury historical date-bounded query | 7 days or longer |
| Regulations docket/document | 6 hours; comments 1 hour |
| GovInfo package/granule by ID | 30 days, keyed/revalidated by `lastModified` |

### 6.2 Source rate policies

| Source | Default internal policy |
|---|---|
| SEC | 5 requests/second, burst 2, concurrency 2 |
| Congress.gov | 1 request/second, burst 3, concurrency 2 |
| Federal Register | 2 requests/second, burst 2, concurrency 2 |
| USAspending | 1 request/second, burst 2, concurrency 2 |
| Treasury | 2 requests/second, burst 2, concurrency 2 |
| Regulations.gov | 1 request/4 seconds, burst 2, concurrency 1 |
| GovInfo | 5 requests/second, burst 3, concurrency 2 |

These are application defaults, not claims about unpublished agency quotas. They may be lowered through configuration but should not be raised above a published limit. Always prefer `Retry-After`, `X-RateLimit-*`, and equivalent response headers when they are more restrictive.

Retry only idempotent/read operations and allowlisted read-only POST searches. Retry 429, 502, 503, and 504 with full-jitter exponential backoff, at most three attempts, respecting `Retry-After`. Use bounded connect/read/total timeouts. Do not retry most 4xx responses. Surface source name, status, and a safe remediation message without printing keys or full request headers.

### 6.3 Per-query ceilings

Defaults, all configurable downward:

- `tool_calls_limit = 8` successful model-invoked tools.
- `request_limit = 6` model requests, including the initial request and one citation-repair turn.
- `http_requests_limit = 20` actual outbound government requests, including internal pagination but excluding cache hits; retries count.
- `max_pages_per_tool = 3`.
- `max_records_per_tool = 10`.
- `max_single_download = 20 MiB`; stream and abort above it unless a specifically allowlisted larger SEC filing is handled by section extraction.
- `max_evidence_chars_per_record = 12,000` and a total evidence/token budget before the next model turn.
- A provider cost limit of roughly `$0.05` per default run where provider usage accounting supports it, plus token ceilings as the provider-independent backstop.

Pydantic AI checks request/tool limits before the next operation. The application-level HTTP budget prevents a single high-level tool from hiding unbounded pagination underneath one model tool call.

### 6.4 Failure behavior

- Return structured tool errors (`source`, safe status, retryability, suggestion) rather than fake empty evidence.
- Partial source outages do not erase already collected evidence. The final answer states which requested source could not be checked.
- If no primary evidence supports an answer, say so and show the attempted official sources; do not answer from model memory.
- If the citation validator still fails after one repair, exit non-zero and print the evidence/source list with an explicit synthesis failure.
- Record a per-run trace locally with secrets redacted: query ID, cache hits, endpoints without query keys, durations, retry counts, tool call count, model/token usage, evidence IDs, and validation outcome.

## 7. Proposed package boundaries for Phase 3

This was the architectural layout approved at the end of Phase 1 and is now implemented:

```text
src/us_gov_research/
  cli.py                  CLI parsing and rendering
  config.py               environment-only settings
  agent.py                one Pydantic AI agent and limits
  evidence.py             normalized records and citation validation
  http.py                 allowlists, cache, rate limits, retry, budgets
  cache.py                SQLite/blob cache
  tools/
    sec.py
    congress.py
    federal_register.py
    usaspending.py
    treasury.py
    regulations.py
    govinfo.py
tests/
  unit/                   fixtures only; network and model calls blocked
  contract/               recorded/sanitized schemas and live opt-in checks
  acceptance/             cited answer and source-routing scenarios
```

The HTTP layer owns credentials and required headers. Tool functions receive safe clients through dependency injection, which makes them easy to test and prevents the model from seeing secrets.

## 8. Test strategy implied by the architecture

- Unit-test every input schema, endpoint allowlist, query normalization, response normalizer, cache key, rate-limit branch, retry classification, and error redaction.
- Globally block real LLM requests in normal tests and use Pydantic AI `TestModel`/`FunctionModel` to simulate single, sequential, parallel, malformed, and runaway tool calls.
- Use sanitized fixtures that contain no keys, authorization headers, personal SEC contact string, or sensitive query parameters.
- Add contract tests for representative live endpoints, but make them opt-in locally and use only repository CI secrets owned by the repository—not a developer's `.env`.
- Acceptance tests must verify that Tesla resolves to the correct CIK, the latest relevant 10-K is selected by filing date/form, Item 1A or the equivalent risk-factor section is extracted, every synthesized claim cites the accession's official SEC URL, and no unsupported claim survives citation validation.
- Include coverage-limit tests: Congress Senate vote requests, missing Regulations fields, SEC custom XBRL tags, empty USAspending results, GovInfo 503 generation, and unpublished-rate-limit sources returning 429.

## 9. Decisions deferred to Phase 2 review

After this architecture is approved, Phase 2 should establish publication safety **before application code**:

- `.gitignore` containing `.env` before the repository's first commit.
- `.env.example`, README key setup, `SECURITY.md`, MIT `LICENSE`, gitleaks pre-commit configuration, and CI history/working-tree scanning.
- Environment variable names and required/optional key rules, including whether one `DATA_GOV_API_KEY` is reused for the three api.data.gov-backed sources.
- A repository-wide and full-history secret scan before the final commit. At present there is no git history and no key has been introduced.

No Phase 2 or Phase 3 work should begin until this document is reviewed and the architecture decision is accepted or amended.

## 10. Optional Hermes Agent runtime

Hermes support is an adapter around the accepted architecture, not a second agent. The package
exposes all seven existing adapters as typed tools on one local stdio MCP server. Hermes owns tool
selection, parallelization, context, and synthesis; the MCP process owns official-API access,
normalization, caching, request budgets, and source-specific throttling. This avoids nested model
calls and their duplicate cost, latency, and debugging surface.

Design choices:

- `mcp>=2,<3` is an optional `hermes` dependency; standalone CLI users do not install it.
- Every MCP invocation receives a fresh HTTP request budget. Source rate limiters are shared for
  the lifetime of the server, so parallel Hermes calls cannot each claim a separate quota.
- Tools return the existing `EvidenceRecord` shape as structured output, including the official
  `canonical_url`. They do not synthesize, invoke a model, expose arbitrary URLs, or mutate data.
- The MCP server reads government credentials from an explicitly selected ignored dotenv file.
  Hermes' checked-in configuration example contains path substitutions only, never credentials.
- MCP sampling, prompts, and resources are disabled because the server requires tools only.
- `supports_parallel_tool_calls` is enabled because the tools are independent and read-only.
- A project-local Hermes skill supplies source routing, prompt-injection resistance, date
  semantics, failure behavior, and inline primary-citation rules.

This runtime retains the same cache and outbound HTTP ceiling per call. Hermes itself must enforce
its own turn/tool ceiling; the included skill instructs it to start narrow and expand only when
evidence is insufficient.
