# US Gov Research Agent

An open-source command-line AI research agent for SEC filings and official U.S. federal government data. It calls primary public APIs, normalizes the evidence, and produces a synthesized answer with clickable citations for every material claim.

The agent is deliberately small: one model, seven typed read-only tools, a local cache, and hard request/token ceilings. See [ARCHITECTURE.md](ARCHITECTURE.md) for the researched API limits and design decision.

> **Installing with an AI agent?** The agent must read
> [AGENT_INSTALL.md](AGENT_INSTALL.md) first. Its first response must explain which user-supplied
> credentials are needed and pause for credential readiness. It must not install or test until the
> user later confirms the ignored `.env` is configured. Never paste API keys into chat.

## Data sources

| Tool | Official source | Key |
|---|---|---|
| SEC filings and XBRL | SEC EDGAR | Keyless; descriptive `User-Agent` required |
| Bills, members, House votes | Congress.gov API v3 | Free api.data.gov key |
| Rules, notices, executive actions | Federal Register API | Keyless |
| Contracts, grants, awards | USAspending.gov API | Keyless |
| Debt and federal financial series | Treasury Fiscal Data API | Keyless |
| Dockets and public comments | Regulations.gov API v4 | Free api.data.gov key |
| Official federal publications | GovInfo API | Free api.data.gov key |

Regulations.gov is exposed as GET-only. The agent cannot post public comments or mutate any government system.

USAspending requires each search to target one official award-type group. The typed tool lets the model choose contracts, grants, loans, direct payments, other financial assistance, or IDVs explicitly.

## Requirements

- Python 3.11 or 3.12
- An LLM provider API key for the standalone CLI; the default uses OpenAI
- A real contact email for the SEC `User-Agent`
- One free api.data.gov key for Congress.gov, Regulations.gov, and GovInfo

## Setup & API Keys

### 1. Clone and install

```bash
git clone https://github.com/snobistisch/us-gov-research-agent.git
cd us-gov-research-agent
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

### 2. Create local configuration

```bash
cp .env.example .env
```

Edit `.env` and replace the placeholders. `.env` is ignored by git and must never be committed.

| Variable | Required | Where to obtain it |
|---|---|---|
| `LLM_MODEL` | Yes | Provider/model selector. The default `openai-responses:gpt-5.6-luna` is inexpensive and supports function calling. |
| `OPENAI_API_KEY` | For the default model | Create your own key at [OpenAI API keys](https://platform.openai.com/api-keys). API usage is paid; never reuse the original author's key. |
| `SEC_USER_AGENT` | Yes | No key. Use your real name/organization and contact email, such as `Jane Doe jane@domain.tld`, as required by SEC automated-access policy. |
| `DATA_GOV_API_KEY` | For Congress, Regulations, GovInfo | Register free at [api.data.gov](https://api.data.gov/signup/). One key works with all three sources. |

Federal Register, USAspending, and Treasury Fiscal Data require no key.

### 3. Run a question

```bash
research-agent "What were Tesla's most recently disclosed risk factors?"
```

Other options:

```bash
research-agent --json "What final AI rules did the FTC publish this year?"
research-agent --refresh "How much public debt was outstanding on the latest date?"
research-agent --clear-cache
```

The first command sends data to the selected LLM provider. Official API responses are cached locally in the operating system's user-cache directory; credentials are excluded from cache keys and logs.

## Hermes Agent integration

Hermes can act as the orchestrator and call the same seven read-only source adapters through one
local MCP server. In this mode there is no nested agent or second synthesis call: Hermes plans and
writes the answer, while this package only retrieves normalized primary-source evidence. The
standalone `LLM_MODEL` and `OPENAI_API_KEY` settings are therefore not used by the MCP server.

### Credential gate for AI installers

Before an AI agent runs any command, it must follow [AGENT_INSTALL.md](AGENT_INSTALL.md): explain
that the user must provide `SEC_USER_AGENT` and a free `DATA_GOV_API_KEY`, tell the user to store
them locally in the ignored `.env`, and wait for confirmation. It must not request or repeat raw
credentials in chat. `OPENAI_API_KEY` is not required for Hermes MCP mode because Hermes supplies
the model; it remains necessary for the standalone CLI's default OpenAI configuration.

Install the optional MCP dependency in this repository's virtual environment:

```bash
python -m pip install '.[hermes]'
```

Keep the government API settings in the repository's ignored `.env` file. Then add only these three
non-secret absolute paths to `~/.hermes/.env`:

```dotenv
US_GOV_RESEARCH_AGENT_BIN=/absolute/path/to/us-gov-research-agent/.venv/bin/research-agent-mcp
US_GOV_RESEARCH_AGENT_ENV_FILE=/absolute/path/to/us-gov-research-agent/.env
US_GOV_RESEARCH_AGENT_SKILLS_DIR=/absolute/path/to/us-gov-research-agent/.hermes/skills
```

Merge [`hermes/config.example.yaml`](hermes/config.example.yaml) into
`~/.hermes/config.yaml`. The configuration enables parallel calls for independent read-only
research, disables MCP sampling, and deliberately keeps credentials out of Hermes' YAML file.
Validate and start it with:

```bash
hermes mcp test us_gov_research
hermes chat
```

The configured external skills directory makes Hermes discover the citation and source-routing
instructions in [`.hermes/skills/sec-federal-research/SKILL.md`](.hermes/skills/sec-federal-research/SKILL.md)
from any working directory.
The exposed names are prefixed by Hermes, for example
`mcp_us_gov_research_sec_filings`. A useful acceptance prompt is:

```text
What were Tesla's most recently disclosed risk factors? Cite the SEC filing for every claim.
```

Only SEC searches require `SEC_USER_AGENT`. Congress.gov, Regulations.gov, and GovInfo require
`DATA_GOV_API_KEY`; the remaining three sources are keyless. Missing credentials fail only the
affected tool, so keyless research remains available.

## Model/provider choice

`LLM_MODEL` uses Pydantic AI's `provider:model` syntax. To switch providers, change that one variable and supply the new provider's conventional key variable. For example:

```dotenv
LLM_MODEL=anthropic:your-supported-model-id
ANTHROPIC_API_KEY=replace-with-your-own-key
```

Install the corresponding Pydantic AI provider extra if it is not part of your environment. Model behavior differs, so run the tests and a representative live query after switching.

The default OpenAI model is currently priced for cost-sensitive workloads. Normal questions are expected to cost roughly one or two cents or less, but document length and tool-loop behavior vary. The CLI reports provider usage when available and enforces configurable limits.

## Reliability and limits

Defaults:

- 8 successful model tool calls
- 6 model requests
- 20 outbound government HTTP requests, including retries and internal pagination
- At most 10 normalized records from a tool
- 20,000 cumulative input tokens, 10,000 cumulative output tokens, and 2,000 output tokens per model response
- Source-specific throttling below published limits

The agent retries transient 429/502/503/504 responses with jitter and honors `Retry-After`. It fails rather than answering from model memory when it retrieves no official evidence. SEC filing documents are cached by immutable accession URL. At Luna's documented prices, the default token caps keep the normal orchestration run below `$0.05`; a one-request citation repair is separately capped. Swapping to a more expensive provider/model requires recalibrating these token limits.

Known coverage limitations are documented in [ARCHITECTURE.md](ARCHITECTURE.md), including the best-effort status of SEC's full-text UI backend and the lack of equivalent comprehensive Senate vote endpoints in Congress.gov API v3.

## Security and secret scanning

Install the Gitleaks pre-commit hook for development:

```bash
python -m pip install '.[dev]'
pre-commit install
pre-commit run --all-files
```

GitHub Actions also runs Gitleaks against the complete repository history on every push and pull request. See [SECURITY.md](SECURITY.md) for key rotation and private vulnerability reporting.

If a secret is ever committed, revoke it first. A later deletion does not remove it from git history.

## Development

```bash
python -m pip install '.[dev]'
ruff check .
pytest
```

Normal tests block real model calls and use sanitized fixtures. Live contract tests, when added or enabled, must use a contributor's own environment keys and must never print or record request authentication.

## How citations work

Each adapter returns normalized evidence with an official canonical URL. The model cites registered evidence IDs such as `[S1]`. A deterministic renderer rejects unknown IDs and non-official hosts, converts valid markers into links, and appends the primary-source list. Search pages are used for discovery; final citations prefer the actual filing, bill, document, award, dataset, docket, or GovInfo package.

## License

MIT. See [LICENSE](LICENSE).
