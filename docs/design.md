# Design: rootcoz weekly Slack digest

## Goal

On a configurable Cron schedule, query the **rootcoz API** for the last complete
Sun–Sat week and post a Slack message (job, tier, failures, reviewed, links).
Optional HTML email delivery uses the same API rows.

## Boundaries

| In scope | Out of scope |
|----------|--------------|
| Slack / email digest from rootcoz API | HTML reports (`rootcause-summary` / coverage) |
| Configurable columns / message templates | Changing rootcoz analysis/review |
| Team usergroup mentions + email recipients | Maintaining individual people lists in git |

## Data path (mandatory)

```text
Bearer auth → GET /api/dashboard/filtered → format message → Slack and/or email
```

No HTML summary URLs. When a team has zero unreviewed failures, a celebration
message is posted instead of a digest table — either "Zero failures this week"
or "All N failures reviewed". Templates live under `[message]`.

## Data Flow

- **Week window:** last complete Sun–Sat in UTC (computed by `week.py`)
- **Rootcoz API:** `GET /api/dashboard/filtered` with `Authorization: Bearer <api_key>`,
  `date_from`/`date_to`, `review_status=not_reviewed`, and `limit=0`
- **Job links:** rootcoz `/results/{job_id}`; Jenkins URLs from the API response
  (`jenkins_url` / `build_url`)
- **Routing:** `TARGETS` JSON maps each team to optional Slack (`channel` + `usergroup`)
  and/or email (`recipients` + optional `cc`)

## Configurability

| Area | Config |
|------|--------|
| Cron | `[schedule] cron` is a sync marker — CronJob `spec.schedule` triggers runs; week window is always UTC |
| Columns | `[digest] columns` ordered list |
| Message | `[message] format` + templates |
| Email SMTP | `[email]` host/port/from/tls; delivery toggled with `enabled` |

## Mentions / recipients

`TARGETS` JSON env maps team → Slack and/or email. Slack usergroup membership is managed in
Slack. Runtime resolves handle → `<!subteam^ID>` (`usergroups:read` + bot token).

Webhook mode (`slack.mode = "webhook"`) supports at most one `TARGETS` entry with Slack;
use bot mode for multi-target channel routing. Email-only targets do not count toward that limit.

## Deploy

Namespace `REPLACE_NAMESPACE`. Secret for credentials; ConfigMap for `config.toml`;
ConfigMap also provides `ROOTCOZ_URL`, `ROOTCOZ_VERIFY_SSL`, and `TARGETS` (mandatory JSON routing).
CronJob schedule must match `[schedule].cron`.
