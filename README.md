# rootcoz-slack-digest

Weekly Slack digest of [rootcoz](https://github.com/myk-org/rootcoz) failures and
review progress for CNV QE teams.

Posts a table (job, tier, failures, reviewed, Jenkins + rootcoz links) for the
last complete Monday–Sunday week. Teams are CC'd via **Slack usergroups** they
manage themselves.

## Quick start

```bash
git clone git@github.com:REPLACE_ORG/rootcoz-slack-digest.git
cd rootcoz-slack-digest
uv sync --group dev
cp config/config.example.toml config/config.toml
# set ROOTCOZ_URL, ROOTCOZ_USERNAME, ROOTCOZ_API_KEY, SLACK_BOT_TOKEN, SLACK_CHANNEL
uv run rootcoz-slack-digest run --config config/config.toml --dry-run
```

## CLI

| Command | Description |
|---------|-------------|
| `rootcoz-slack-digest run` | Fetch week + post (or `--dry-run`) |
| `rootcoz-slack-digest render` | Alias for dry-run JSON to stdout |

Flags (`--config`, `--from`, `--to`, `--dry-run`, `--verbose`) also have
equivalents in `config.toml` under `[digest]`, `[rootcoz]`, `[slack]`,
`[mentions.teams]`.

## Mentions (no people lists in git)

```toml
[mentions.teams]
network = "network-qe"
```

Membership of `@network-qe` is edited in Slack by that team. This repo only
stores the stable handle map.

Requires Slack bot scopes: `chat:write`, `usergroups:read`.

## Deploy (OpenShift)

Manifests under `deploy/` target namespace `REPLACE_NAMESPACE`:

1. Create Secret `rootcoz-slack-digest-credentials` (includes `GITHUB_TOKEN` so the
   CronJob can `pip install` this private repo)
2. Apply ConfigMap + CronJob (`0 7 * * 0` Sunday 07:00 UTC)
3. Manual test: `oc create job --from=cronjob/rootcoz-slack-digest manual-$(date +%s) -n REPLACE_NAMESPACE`

Does **not** replace the HTML rootcause summary at
`rootcause-summary-REPLACE_NAMESPACE`.

## Development

```bash
uv run ruff check src tests
uv run ruff format src tests
uv run pytest
pre-commit run --all-files
```

See [docs/design.md](docs/design.md) and [AGENTS.md](AGENTS.md).
