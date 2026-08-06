# Design: rootcoz weekly Slack digest

## Goal

Every Sunday, post a Slack message summarizing the last complete Mon–Sun week of
rootcoz analysis for CNV QE: job name, tier, failures, reviewed, Jenkins link,
rootcoz link.

## Boundaries

| In scope | Out of scope |
|----------|--------------|
| Slack digest + OpenShift CronJob | HTML reports (`rootcause-summary`) |
| rootcoz API consumer | Changing rootcoz analysis/review |
| Team usergroup mentions | Maintaining individual people lists |

## Mentions

Config maps `team → Slack usergroup handle`. Membership is managed in Slack by
each team. Runtime resolves handle → `<!subteam^ID>` via `usergroups.list`
(requires bot token + `usergroups:read`).

## Data

- Window: last complete Mon–Sun UTC (`week.last_complete_week`)
- API: `GET /api/reports/totals?from=&to=&status=completed&tier=&team=`
- Links: rootcoz `/results/{job_id}`; Jenkins from env `JENKINS_URL` + job/build

## Deploy

Namespace `cnv-rootcoz`. Secret for credentials; ConfigMap for `config.toml`;
CronJob `0 7 * * 0`.
