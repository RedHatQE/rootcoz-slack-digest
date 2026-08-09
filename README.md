# rootcoz-slack-digest

Slack digest of [rootcoz](https://github.com/myk-org/rootcoz) failures and review
progress for CNV QE teams.

**Data source:** rootcoz HTTP API only (`/api/reports/totals` + job metadata).
This tool does **not** use or link to HTML coverage/rootcause summary pages.

On a configurable schedule (or on demand via CLI), it queries rootcoz for a date
window (default: last complete Mon–Sun), formats a configurable table (job, tier,
failures, reviewed, Jenkins + rootcoz links), and posts to Slack. Teams are CC'd
via **Slack usergroups** they manage themselves.

## Quick start

```bash
git clone git@github.com:RedHatQE/rootcoz-slack-digest.git
cd rootcoz-slack-digest
uv sync --group dev
cp config/config.example.toml config/config.toml
# set ROOTCOZ_URL, ROOTCOZ_USERNAME, ROOTCOZ_API_KEY, SLACK_BOT_TOKEN, SLACK_CHANNEL
uv run rootcoz-slack-digest run --config config/config.toml --dry-run
```

## CLI

| Command | Description |
|---------|-------------|
| `rootcoz-slack-digest run` | Query API + post (or `--dry-run`) |
| `rootcoz-slack-digest render` | Alias for dry-run payload to stdout |

Flags (`--config`, `--from`, `--to`, `--dry-run`, `--verbose`) also have
equivalents in `config.toml`.

## Configuration highlights

```toml
[schedule]
cron = "0 7 * * 0"          # any cron; keep deploy/cronjob.yaml in sync

[digest]
columns = ["job_name", "tier", "failures", "reviewed", "jenkins", "rootcoz"]

[message]
format = "blocks"           # blocks | mrkdwn | plain
header_template = "*rootcoz digest* — {week_label}{mention_suffix}"
```

See `config/config.example.toml` for all keys (columns, message templates, tiers,
teams, mentions).

## Mentions (no people lists in git)

```toml
[mentions.teams]
network = "network-qe"
```

Requires Slack bot scopes: `chat:write`, `usergroups:read`.

## Deploy (OpenShift)

Manifests under `deploy/` target namespace `cnv-rootcoz`:

1. Create Secret `rootcoz-slack-digest-credentials`
2. Apply ConfigMap + CronJob — set `spec.schedule` to the same value as
   `[schedule].cron`
3. Manual test: `oc create job --from=cronjob/rootcoz-slack-digest manual-$(date +%s) -n cnv-rootcoz`

## Development

```bash
uv run ruff check src tests
uv run ruff format src tests
uv run pytest
pre-commit run --all-files
```

See [docs/design.md](docs/design.md) and [AGENTS.md](AGENTS.md).
