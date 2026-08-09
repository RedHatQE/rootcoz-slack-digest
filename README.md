# rootcoz-slack-digest

Slack (and optional email) digest of [rootcoz](https://github.com/myk-org/rootcoz)
failures and review progress for CNV QE teams.

**Data source:** rootcoz HTTP API only (`GET /api/dashboard/filtered` with Bearer
auth). This tool does **not** use or link to HTML coverage/rootcause summary pages.
Jenkins and rootcoz result URLs come from the API response (no `JENKINS_URL` env).

On a configurable schedule (or on demand via CLI), it queries rootcoz for a date
window (default: last complete Sun–Sat), formats a configurable table (job, tier,
failures, reviewed, Jenkins + rootcoz links), and posts to Slack and/or email.
Teams are CC'd via **Slack usergroups** they manage themselves.

## Quick start

```bash
git clone git@github.com:REPLACE_ORG/rootcoz-slack-digest.git
cd rootcoz-slack-digest
uv sync --group dev
cp config/config.example.toml config/config.toml
# set ROOTCOZ_URL, ROOTCOZ_API_KEY, SLACK_BOT_TOKEN, TARGETS
uv run rootcoz-slack-digest run --config config/config.toml --dry-run
```

## CLI

| Command | Description |
|---------|-------------|
| `rootcoz-slack-digest run` | Query API + post (or `--dry-run`) |
| `rootcoz-slack-digest render` | Alias for dry-run payload to stdout |

`--config` selects the TOML file. `--from`, `--to`, `--dry-run`, and
`--verbose` are **CLI-only** (not TOML keys).

`--dry-run` / `render` print one Block Kit payload per `TARGETS` entry
(with a target header), or `(no matching targets to render)` if none match.

## Configuration highlights

TOML sections: `schedule`, `digest`, `message`, `slack`, `rootcoz`, `email`.

```toml
[schedule]
# Sync marker only — OpenShift CronJob spec.schedule is what triggers runs.
# Week window is always Sun–Sat UTC (timezone setting is unused).
cron = "0 7 * * 0"

[digest]
columns = ["job_name", "tier", "failures", "reviewed", "jenkins", "rootcoz"]
# Also: exclude_labels, exclude_job_patterns, exclude_versions, include_tags,
# sort_by, max_rows, tiers

[message]
format = "blocks"           # blocks | mrkdwn | plain
header_template = "*rootcoz digest* — {week_label}{excluded_versions}{mention_suffix}"
# Also: celebration_*_template, email_subject_template, totals/row/omitted templates

[rootcoz]
# field_map, tier_labels (incl. default_tier), bundle_pattern, endpoint/params

[email]
enabled = false
```

See `config/config.example.toml` for all keys (columns, message templates, tiers,
`exclude_labels`, `exclude_job_patterns`, `exclude_versions`, `include_tags`,
celebration templates, `email_subject_template`, `bundle_pattern`, `default_tier`,
and more).
Team routing is via `TARGETS`, not `[digest]` config.

## Mentions (no people lists in git)

```text
# Team routing via TARGETS env / ConfigMap (JSON):
#   [{"team": "virt-node",
#     "slack": {"channel": "C...", "usergroup": "virt-node-qe"},
#     "email": {"recipients": ["team@example.com"], "cc": []}}]
```

Each entry posts a team-filtered digest — rows are matched by `row.team == target.team`.
When a team has zero unreviewed failures, a **celebration** message is posted instead:
- **Zero failures this week** — no failures at all for that team
- **All N failures reviewed** — failures existed but all were reviewed
Celebration templates (`celebration_no_failures_template`,
`celebration_reviewed_template`) are configurable under `[message]`.
Team strings must exactly match rootcoz job metadata.
If jobs exist but no team matches any `TARGETS` entry, the run fails with an error (likely a team name mismatch in config).
Dry-run prints `(no matching targets to render)` when nothing matches.
Multi-target Slack routing requires `slack.mode = "bot"`; webhook mode supports at most one `TARGETS` entry with Slack.

Requires Slack bot scopes: `chat:write`, `usergroups:read`.

## Deploy (OpenShift)

Manifests under `deploy/` target namespace `REPLACE_NAMESPACE`.
The CronJob installs the package from the **public** GitHub repo via
`git+https` (no `GITHUB_TOKEN` required).

| Source | Keys |
|--------|------|
| **ConfigMap** | `ROOTCOZ_URL`, `ROOTCOZ_VERIFY_SSL`, `TARGETS` (JSON array, **mandatory** for posting) |
| **Secret** | `ROOTCOZ_API_KEY`, `SLACK_BOT_TOKEN` |

`TARGETS` format:

```json
[
  {
    "team": "virt-node",
    "slack": {"channel": "C...", "usergroup": "virt-node-qe"},
    "email": {"recipients": ["team@example.com"]}
  }
]
```

1. Create Secret `rootcoz-slack-digest-credentials`
2. Apply ConfigMap + CronJob — set CronJob `spec.schedule` to match
   `[schedule].cron` in the ConfigMap (the TOML value is a sync marker only;
   the CronJob schedule is what actually triggers runs)
3. Manual test: `oc create job --from=cronjob/rootcoz-slack-digest manual-$(date +%s) -n REPLACE_NAMESPACE`

### Staging

Manifests under `deploy/staging/` post to a test Slack channel only
(`suspend: true` — trigger manually). Reuses the production Secret for
credentials; apply ConfigMap + CronJob separately from prod.

```bash
oc apply -f deploy/staging/configmap.yaml -f deploy/staging/cronjob.yaml -n REPLACE_NAMESPACE
oc create job --from=cronjob/rootcoz-slack-digest-staging staging-$(date +%s) -n REPLACE_NAMESPACE
```

## Development

```bash
uv run ruff check src tests
uv run ruff format src tests
uv run pytest
pre-commit run --all-files
```

See [docs/design.md](docs/design.md) and [AGENTS.md](AGENTS.md).
