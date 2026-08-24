# AI Agent Installation Contract

This file is written for AI agents that install, configure, or evaluate this repository.

## Mandatory first response: credential handoff

**Stop before running any install, configuration, or test command.** Your first response to the
user must explain that this project needs credentials supplied by the user. Ask whether the user
has their own values ready. Do not run a command until they confirm credential readiness. If the
repository and its ignored `.env` already exist, ask them to configure it and reply `configured`.
If the repository does not exist yet, explain that you will clone it, safely create the ignored
`.env` template, and then pause so they can fill it locally.

Use wording equivalent to:

> Before I install or test this project, you need to supply your own configuration. SEC research
> requires `SEC_USER_AGENT` with your real name or organization and a monitored contact email;
> placeholder and `noreply` addresses are rejected. Congress.gov,
> Regulations.gov, and GovInfo require one free `DATA_GOV_API_KEY` from
> https://api.data.gov/signup/. Hermes MCP mode uses Hermes' existing model provider, so it does
> not need `OPENAI_API_KEY`; that key is needed only for the standalone `research-agent` CLI with
> its default model. Put the values in the repository's ignored `.env` file—do not paste keys into
> chat. If the repository is not cloned yet, reply “ready”; I will prepare the ignored template
> and pause again for you to fill it. If `.env` already exists, reply “configured” when it is ready.

Do not ask the user to paste raw keys into chat, a prompt, a ticket, a commit, or a terminal command
that could be logged. Never read, echo, print, summarize, or include `.env` values in your output.
If the user accidentally reveals a key, tell them to revoke and replace it before continuing.

### Credential matrix

| Setting | Hermes MCP | Standalone CLI | Source |
|---|---|---|---|
| `SEC_USER_AGENT` | Required for SEC tools | Required | No key; use a real contact identity |
| `DATA_GOV_API_KEY` | Required for Congress.gov, Regulations.gov, and GovInfo | Same | Free: https://api.data.gov/signup/ |
| `OPENAI_API_KEY` | Not used | Required only for the default OpenAI model | Paid: https://platform.openai.com/api-keys |
| `LLM_MODEL` | Not used | Required model selector | Defaults to `openai-responses:gpt-5.6-luna` |

Federal Register, USAspending, and Treasury Fiscal Data are keyless. Missing credentials must
disable only the affected tools; never invent a credential or silently fall back to model memory.

## Safe installation sequence

After the user confirms credential readiness:

1. Clone or open the repository and read `README.md`, `SECURITY.md`, and this file.
2. Verify that `.gitignore` contains `.env`, `.env.*`, and `!.env.example` **before** creating or
   touching `.env`. Confirm with `git check-ignore .env`; it must report `.env` as ignored.
3. Never replace an existing `.env`. If it is absent, copy `.env.example` to `.env`. Stop and ask
   the user to fill it locally. Do not continue until the user replies `configured`. If `.env`
   already existed, obtain the same confirmation without reading or printing it.
4. Only after that confirmation, create `.venv`, then install with
   `python -m pip install '.[hermes,dev]'`. Use a normal wheel
   install, not an editable install.
5. Merge `hermes/config.example.yaml` into the existing `~/.hermes/config.yaml`. Preserve all
   unrelated user settings; do not overwrite the file wholesale.
6. Add the three non-secret absolute path variables documented in `README.md` to
   `~/.hermes/.env`. Do not copy government API keys into Hermes' YAML configuration.
7. Run `hermes mcp test us_gov_research` and verify that exactly seven tools are discovered.

All source operations are read-only. Do not post a Regulations.gov comment, mutate a government
system, or add arbitrary URLs, HTTP methods, shell access, or filesystem access to the MCP server.

## Required verification

Run and record pass/fail status without exposing environment values:

```bash
ruff check .
pytest
pre-commit run --all-files
git status --short
hermes mcp test us_gov_research
```

With the user's ignored `.env` configured, run the opt-in SEC contract test without printing any
environment value:

```bash
RUN_LIVE_SEC_CONTRACT=1 pytest tests/test_sec.py -k live_sec_contract
```

Then perform these live behavioral checks through Hermes:

1. **SEC acceptance:** “What were Tesla's most recently disclosed risk factors?” Confirm that the
   newest relevant filing is used and every material claim links to the official SEC filing.
2. **Keyless source:** Ask for the latest Debt to the Penny record or a recent Federal Register
   document. Confirm that units and relevant dates are preserved and citations use official URLs.
3. **api.data.gov source:** Run a small Congress.gov query. Confirm that the configured key works,
   but never include the key or authenticated request details in the report. Search for member
   `Elizabeth Warren` with `current_member=true` and confirm bioguide ID `W000817`, normalized name,
   and party. Then query exact ID `W000817` and confirm the detail route returns the same identity.
4. Repeat one query and note whether the second run benefits from the cache without claiming exact
   performance guarantees from a single observation.
5. Check failure behavior with a deliberately missing key only in an isolated test environment.
   Confirm that the error names the missing variable, reveals no value, and does not block keyless
   tools. Restore the environment immediately afterward.

Do not weaken or bypass the request, tool, token, host-allowlist, citation, or rate-limit controls
to make a test pass.

## Required final evaluation report

Return one concise Markdown report that another developer or AI agent can use to improve the
project. Never include secret values, personal contact data, full request headers, `.env` contents,
or authentication-bearing URLs.

Use this structure:

```markdown
# Hermes Installation and Evaluation Report

## Environment
- OS, architecture, Python version, Hermes version, package commit
- Credential readiness: SEC configured yes/no; api.data.gov configured yes/no; values redacted

## Installation
- Commands or high-level actions performed
- MCP connection result and the seven discovered tool names

## Automated checks
- Ruff, pytest test count, pre-commit/Gitleaks, git status

## Live scenarios
For each scenario: prompt, selected tool(s), pass/fail, source URL hosts, citation assessment,
date/unit assessment, observed errors, and approximate elapsed time. Do not reproduce keys.

## Findings
- Numbered findings ordered by severity: P0 security/data loss, P1 broken core behavior,
  P2 reliability/grounding, P3 usability/maintainability
- For each: evidence, reproduction steps, expected behavior, actual behavior, suggested fix

## Improvement backlog
- Concrete, prioritized changes with likely file/module and a verification test

## Verdict
- Ready / ready with limitations / not ready
- Three highest-value next actions
```

Do not report a test as passed unless you observed its success. Separate repository defects from
local setup problems and external API outages.
