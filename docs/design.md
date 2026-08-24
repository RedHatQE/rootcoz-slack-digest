# Design: rootcoz weekly Slack digest

## Goal

On a configurable Cron schedule, query the **rootcoz API** for the last complete
Sun–Sat week (default; optional Mon–Sun via `week_start`) and post a Slack message
(job, bundle, reviewed, links by default).
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

### Optional Jenkins miss-check (Slack)

When `[jenkins.miss_check] enabled = true`, before Slack post the digest may:

1. List non-success builds from a Jenkins view (`FAILURE`/`UNSTABLE` by default;
   never `SUCCESS`)
2. Keep only gating jobs: name contains `require_name_substring` (default `gating`)
   and `JOB_METADATA.labels` includes `require_labels` (default `gate`) — drops
   non-gating view members such as `test-ssp-cnv-4.18`
3. Read `JOB_METADATA.team` and map via `[jenkins.team_map]` to TARGETS slugs;
   read bundle from `DATA_BUNDLE_VERSION`
4. Diff against rootcoz inventory; merge misses into the **same** Slack digest
   table with rootcoz=`missing` (Job / Bundle / reviewed / rootcoz)
5. If Jenkins is down: still send rootcoz digests + Slack comment
6. If rootcoz is down: per-team Slack digests from Jenkins + comment; include
   rootcoz `/results/` links when found on the job/build

Jenkins credentials: `JENKINS_USER` / `JENKINS_TOKEN` (Secret). Non-secrets:
`JENKINS_URL`, `JENKINS_VERIFY_SSL` (ConfigMap). Committed examples use
`REPLACE_*` only — never real hosts or tokens.

## Data Flow

- **Week window:** last complete week in UTC (`week.py`; default Sun–Sat, or Mon–Sun when `week_start = "monday"`)
- **Rootcoz API:** `GET /api/dashboard/filtered` with `Authorization: Bearer <api_key>`,
  `date_from`/`date_to`, `review_status=not_reviewed`, and `limit=0`. Multiple digest
  `tiers` are queried as separate `label=` requests and merged (OR); the API ANDs
  multiple labels in one request.
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
ConfigMap also provides `ROOTCOZ_URL`, `ROOTCOZ_VERIFY_SSL`, optional
`JENKINS_URL` / `JENKINS_VERIFY_SSL`, and `TARGETS` (mandatory JSON routing).
Secret holds `ROOTCOZ_API_KEY`, `SLACK_BOT_TOKEN`, and optional
`JENKINS_USER` / `JENKINS_TOKEN`. CronJob schedule must match `[schedule].cron`.
