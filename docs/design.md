# Design: rootcoz weekly Slack digest

## Goal

On a configurable Cron schedule, query the **rootcoz API** for the last complete
Mon–Sun week and post a Slack message (job, tier, failures, reviewed, links).

## Boundaries

| In scope | Out of scope |
|----------|--------------|
| Slack digest from rootcoz API | HTML reports (`rootcause-summary` / coverage) |
| Configurable columns / message templates | Changing rootcoz analysis/review |
| Team usergroup mentions | Maintaining individual people lists |

## Data path (mandatory)

```text
login → GET /api/reports/totals (+ metadata) → format message → Slack
```

No HTML summary URLs. If the API returns nothing useful, the message says so.

## Configurability

| Area | Config |
|------|--------|
| Cron | `[schedule] cron` (keep `deploy/cronjob.yaml` in sync) |
| Columns | `[digest] columns` ordered list |
| Message | `[message] format` + templates |

## Mentions

`[mentions.teams]` maps team → Slack usergroup handle. Membership is managed in
Slack. Runtime resolves handle → `<!subteam^ID>` (`usergroups:read` + bot token).

## Deploy

Namespace `REPLACE_NAMESPACE`. Secret for credentials; ConfigMap for `config.toml`;
CronJob schedule must match `[schedule].cron`.
