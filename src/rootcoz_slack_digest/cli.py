"""Typer CLI for rootcoz-slack-digest."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from rootcoz_slack_digest.models import load_config
from rootcoz_slack_digest.service import render_payload, run_digest

app = typer.Typer(
    name="rootcoz-slack-digest",
    help="Weekly Slack digest of rootcoz failures and reviews.",
    no_args_is_help=True,
)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


@app.command("run")
def run_cmd(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to config.toml"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Build message but do not post to Slack"),
    ] = False,
    date_from: Annotated[
        str | None,
        typer.Option("--from", help="Override window start YYYY-MM-DD"),
    ] = None,
    date_to: Annotated[
        str | None,
        typer.Option("--to", help="Override window end YYYY-MM-DD"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Debug logging"),
    ] = False,
) -> None:
    """Fetch last week from rootcoz and post (or dry-run) the Slack digest."""
    _setup_logging(verbose)
    cfg = load_config(config)
    df = date.fromisoformat(date_from) if date_from else None
    dt = date.fromisoformat(date_to) if date_to else None
    if (df is None) ^ (dt is None):
        raise typer.BadParameter("Provide both --from and --to, or neither")
    typer.echo(
        f"schedule.cron={cfg.schedule.cron!r} timezone={cfg.schedule.timezone!r}",
        err=True,
    )
    result = run_digest(cfg, dry_run=dry_run, date_from=df, date_to=dt)
    if dry_run:
        if not result.target_results:
            typer.echo("(no matching targets to render)")
            return
        for tr in result.target_results:
            typer.echo(f"# team={tr.target.team} channel={tr.target.channel}")
            typer.echo(render_payload(tr.payload))
    else:
        if result.posted:
            n_jobs = len(result.all_rows)
            n_targets = len(result.target_results)
            typer.echo(f"Posted digest ({n_jobs} jobs, {n_targets} targets).")
        else:
            typer.echo("No failures in window — nothing posted.")


@app.command("render")
def render_cmd(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to config.toml"),
    ] = None,
    date_from: Annotated[
        str | None,
        typer.Option("--from", help="Window start YYYY-MM-DD"),
    ] = None,
    date_to: Annotated[
        str | None,
        typer.Option("--to", help="Window end YYYY-MM-DD"),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Same as ``run --dry-run`` (stdout payload per target)."""
    run_cmd(
        config=config,
        dry_run=True,
        date_from=date_from,
        date_to=date_to,
        verbose=verbose,
    )


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
