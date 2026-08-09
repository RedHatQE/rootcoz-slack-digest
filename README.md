# rootcoz-slack-digest

Slack digest of [rootcoz](https://github.com/myk-org/rootcoz) failures and review
progress for CNV QE teams.

**Data source:** rootcoz HTTP API only (`GET /api/dashboard/filtered` with Bearer
auth). This tool does **not** use or link to HTML coverage/rootcause summary pages.
Jenkins and rootcoz result URLs come from the API response (no `JENKINS_URL` env).

On a configurable schedule (or on demand via CLI), it queries rootcoz for a date
window (default: last complete Mon–Sun), formats a configurable table (job, tier,
failures, reviewed, Jenkins + rootcoz links), and posts to Slack. Teams are CC'd
via **Slack usergroups** they manage themselves.

## Quick start

```bash
git clone git@github.com:REPLACE_ORG/rootcoz-slack-digest.git
cd rootcoz-slack-digest
uv sync --group dev
cp config/config.example.toml config/config.toml
# set ROOTCOZ_URL, ROOTCOZ_API_KEY, SLACK_BOT_TOKEN, SLACK_TARGETS
uv run rootcoz-slack-digest run --config config/config.toml --dry-run
```

## CLI

| Command | Description |
|---------|-------------|
| `rootcoz-slack-digest run` | Query API + post (or `--dry-run`) |
| `rootcoz-slack-digest render` | Alias for dry-run payload to stdout |

`--config` selects the TOML file. `--from`, `--to`, `--dry-run`, and
`--verbose` are **CLI-only** (not TOML keys).

`--dry-run` / `render` print one Block Kit payload per `SLACK_TARGETS` entry
(with a target header), or `(no matching targets to render)` if none match.

## Configuration highlights

TOML sections: `schedule`, `digest`, `message`, `slack`, `rootcoz`.

```toml
[schedule]
# Sync marker only — OpenShift CronJob spec.schedule is what triggers runs.
# Week window is always Mon–Sun UTC (timezone setting is unused).
cron = "0 7 * * 0"

[digest]
columns = ["job_name", "tier", "failures", "reviewed", "jenkins", "rootcoz"]

[message]
format = "blocks"           # blocks | mrkdwn | plain
header_template = "*rootcoz digest* — {week_label}{mention_suffix}"
```

See `config/config.example.toml` for all keys (columns, message templates, tiers).
Team routing is via `SLACK_TARGETS`, not `[digest]` config.

## Mentions (no people lists in git)

```text
# Team → channel routing via SLACK_TARGETS env / ConfigMap (JSON):
#   [{"team": "virt-node", "channel": "C...", "usergroup": "virt-node-qe"}]
```

Each entry posts a team-filtered digest to its channel — rows are matched by `row.team == target.team`.
Targets with no matching jobs are skipped (no empty digest posted). Team strings must exactly match rootcoz job metadata.
If no jobs have failures in the window, the run succeeds with nothing posted (quiet week).
If jobs exist but no team matches any `SLACK_TARGETS` entry, the run fails with an error (likely a team name mismatch in config).
Dry-run prints `(no matching targets to render)` in both cases.
Multi-target routing requires `slack.mode = "bot"`; webhook mode supports at most one `SLACK_TARGETS` entry.

Requires Slack bot scopes: `chat:write`, `usergroups:read`.

## Deploy (OpenShift)

Manifests under `deploy/` target namespace `REPLACE_NAMESPACE`.
The CronJob installs the package from the **public** GitHub repo via
`git+https` (no `GITHUB_TOKEN` required).

| Source | Keys |
|--------|------|
| **ConfigMap** | `ROOTCOZ_URL`, `ROOTCOZ_VERIFY_SSL`, `SLACK_TARGETS` (JSON array, **mandatory** for posting) |
| **Secret** | `ROOTCOZ_API_KEY`, `SLACK_BOT_TOKEN` |

`SLACK_TARGETS` format:

```json
[{"team": "virt-node", "channel": "C...", "usergroup": "virt-node-qe"}]
```

1. Create Secret `rootcoz-slack-digest-credentials`
2. Apply ConfigMap + CronJob — set CronJob `spec.schedule` to match
   `[schedule].cron` in the ConfigMap (the TOML value is a sync marker only;
   the CronJob schedule is what actually triggers runs)
3. Manual test: `oc create job --from=cronjob/rootcoz-slack-digest manual-$(date +%s) -n REPLACE_NAMESPACE`

## Development

```bash
uv run ruff check src tests
uv run ruff format src tests
uv run pytest
pre-commit run --all-files
```

See [docs/design.md](docs/design.md) and [AGENTS.md](AGENTS.md).
