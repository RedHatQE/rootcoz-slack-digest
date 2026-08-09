# AGENTS.md — rootcoz-slack-digest

## What this is

Private REPLACE_ORG tool: weekly Slack digest of rootcoz failures/reviews for CNV QE.
Always query the **rootcoz API** before posting. Never depend on HTML summary URLs.

## Layout

- `src/rootcoz_slack_digest/` — application code
- `tests/` — pytest (mirrors modules)
- `config/` — example TOML (real `config.toml` gitignored)
- `deploy/` — OpenShift CronJob / ConfigMap / Secret templates
- `docs/design.md` — product boundaries

## Conventions

- Python ≥ 3.12, managed with `uv`
- Ruff lint + format; pre-commit required
- Builtin types only (`list`, `dict` — not `List`/`Dict`)
- Frozen Pydantic models for config and rows
- No mocks/stubs in `src/` — doubles stay in `tests/`
- Secrets via env / K8s Secret only — never commit tokens
- Team pings = Slack usergroups (`[mentions.teams]`); do not hardcode people

## Commands

```bash
uv sync --group dev
uv run ruff check src tests
uv run pytest
uv run rootcoz-slack-digest run --config config/config.toml --dry-run
```

## Deploy notes

- Namespace: `REPLACE_NAMESPACE`
- Do not edit rootcoz or coverage-reports HTML CronJobs from this repo
