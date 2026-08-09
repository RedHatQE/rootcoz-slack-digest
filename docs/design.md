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

No HTML summary URLs. A week with no failing jobs is a successful no-op — nothing is posted to Slack.

## Data Flow

- **Week window:** last complete Mon–Sun in UTC (computed by `week.py`)
- **Rootcoz API:** `GET /api/reports/totals` with date range + optional team/tier filters
- **Job links:** rootcoz `/results/{job_id}`; Jenkins via `JENKINS_URL` env + job path
- **Routing:** `SLACK_TARGETS` JSON maps each team to a Slack channel + usergroup mention

## Configurability

| Area | Config |
|------|--------|
| Cron | `[schedule] cron` is a sync marker — CronJob `spec.schedule` triggers runs; week window is always UTC |
| Columns | `[digest] columns` ordered list |
| Message | `[message] format` + templates |

## Mentions

`SLACK_TARGETS` JSON env maps team → Slack channel + usergroup handle. Membership is managed in
Slack. Runtime resolves handle → `<!subteam^ID>` (`usergroups:read` + bot token).

Webhook mode (`slack.mode = "webhook"`) supports at most one `SLACK_TARGETS` entry;
use bot mode for multi-target channel routing.

## Deploy

Namespace `REPLACE_NAMESPACE`. Secret for credentials; ConfigMap for `config.toml`;
ConfigMap also provides `ROOTCOZ_URL`, `ROOTCOZ_VERIFY_SSL`, and `SLACK_TARGETS` (mandatory JSON routing).
CronJob schedule must match `[schedule].cron`.
