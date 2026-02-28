"""dnscli — Click-based CLI entry point."""

import getpass
import logging
import sys

import click

from dnsctl.config import LOG_FILE, STATE_DIR
from dnsctl.core.cloudflare_client import CloudflareClient, sanitize_token
from dnsctl.core.git_manager import GitManager
from dnsctl.core.security import get_token, is_logged_in, lock, login, logout, unlock
from dnsctl.core.state_manager import (
    add_protected_record,
    export_zone,
    get_config,
    import_zone,
    init_state_dir,
    list_synced_zones,
    load_protected_records,
    load_zone,
    remove_protected_record,
    save_zone,
    set_config,
)
from dnsctl.core.sync_engine import SyncEngine
from dnsctl.gui.controllers.record_editor_controller import validate_record

logger = logging.getLogger("dnsctl")
_cf = CloudflareClient()
_git = GitManager()
_engine = SyncEngine()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    handlers = [logging.StreamHandler(sys.stderr)]
    # Also log to file if the logs directory exists
    if LOG_FILE.parent.exists():
        handlers.append(logging.FileHandler(str(LOG_FILE), encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def _require_token() -> str:
    """Return the active token or abort with a helpful message."""
    token = get_token()
    if token is None:
        click.echo("Session locked or expired.  Run 'dnscli unlock' first.", err=True)
        raise SystemExit(1)
    return token


# ======================================================================
# CLI group
# ======================================================================

@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output.")
def cli(verbose: bool) -> None:
    """dnsctl — Version-controlled Cloudflare DNS manager."""
    _setup_logging(verbose)


# ======================================================================
# init
# ======================================================================

@cli.command()
def init() -> None:
    """Initialise the dnsctl state directory (~/.dnsctl/)."""
    path = init_state_dir()
    _git.auto_init()
    click.echo(f"Initialised dnsctl state in {path}")


# ======================================================================
# login
# ======================================================================

@cli.command("login")
def login_cmd() -> None:
    """Store a Cloudflare API token (encrypted with a master password)."""
    raw_token = getpass.getpass("Cloudflare API token: ")
    if not raw_token.strip():
        click.echo("Token cannot be empty.", err=True)
        raise SystemExit(1)
    try:
        token = sanitize_token(raw_token)
    except ValueError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)

    # Verify the token against Cloudflare before storing
    click.echo("Verifying token with Cloudflare…")
    try:
        _cf.verify_token(token)
    except Exception as exc:
        click.echo(f"Token verification failed: {exc}", err=True)
        raise SystemExit(1)
    click.echo("Token is valid and active.")

    password = getpass.getpass("Set master password: ")
    confirm = getpass.getpass("Confirm master password: ")
    if password != confirm:
        click.echo("Passwords do not match.", err=True)
        raise SystemExit(1)
    if len(password) < 8:
        click.echo("Password must be at least 8 characters.", err=True)
        raise SystemExit(1)
    login(token, password)
    click.echo("Token encrypted and stored.  Run 'dnscli unlock' to start a session.")





# ======================================================================
# unlock
# ======================================================================

@cli.command("unlock")
def unlock_cmd() -> None:
    """Unlock the session by entering the master password."""
    if not is_logged_in():
        click.echo("No stored token.  Run 'dnscli login' first.", err=True)
        raise SystemExit(1)
    password = getpass.getpass("Master password: ")
    try:
        unlock(password)
    except Exception:
        click.echo("Wrong password or corrupted token.", err=True)
        raise SystemExit(1)
    click.echo("Session unlocked.")





# ======================================================================
# sync
# ======================================================================

@cli.command()
@click.option("--zone", "-z", default=None, help="Zone name to sync.  Omit to sync all.")
def sync(zone: str | None) -> None:
    """Sync DNS records from Cloudflare to local state."""
    init_state_dir()
    token = _require_token()

    zones = _cf.list_zones(token)
    if not zones:
        click.echo("No zones found for this API token.", err=True)
        raise SystemExit(1)

    targets = zones
    if zone:
        targets = [z for z in zones if z["name"] == zone]
        if not targets:
            click.echo(f"Zone '{zone}' not found.  Available: {', '.join(z['name'] for z in zones)}", err=True)
            raise SystemExit(1)

    _git.auto_init()

    for z in targets:
        records = _cf.list_records(token, z["id"])
        state = save_zone(z["id"], z["name"], records)
        click.echo(f"  Synced {z['name']}  ({len(records)} records, hash={state['state_hash'][:12]})")

    sha = _git.commit(f"Sync with remote ({len(targets)} zone(s))")
    if sha:
        click.echo(f"Committed: {sha[:8]}")

    # Set default zone if not set
    cfg = get_config()
    if cfg.get("default_zone") is None and targets:
        set_config("default_zone", targets[0]["name"])


# ======================================================================
# Helpers for diff / plan output
# ======================================================================

def _resolve_zones(zone: str | None) -> list[str]:
    """Resolve a zone argument to a list of zone names."""
    if zone:
        return [zone]
    cfg = get_config()
    default = cfg.get("default_zone")
    if default:
        return [default]
    synced = list_synced_zones()
    if not synced:
        click.echo("No zones synced. Run 'dnscli sync' first.", err=True)
        raise SystemExit(1)
    return synced


def _fmt_record(rec: dict) -> str:
    """One-line summary of a record."""
    parts = [f"{rec.get('type', '?'):6s}", rec.get("name", "?")]
    content = rec.get("content", "")
    if content:
        parts.append(f"→ {content}")
    ttl = rec.get("ttl", 1)
    if ttl != 1:
        parts.append(f"(TTL: {ttl})")
    if rec.get("type") in ("MX", "SRV"):
        parts.append(f"(pri: {rec.get('priority', 0)})")
    return " ".join(parts)


def _print_diff(drift) -> None:
    """Print a DiffResult to stdout."""
    if drift.added:
        click.echo("  Added remotely:")
        for r in drift.added:
            click.echo(click.style(f"    + {_fmt_record(r)}", fg="cyan"))
    if drift.modified:
        click.echo("  Modified remotely:")
        for m in drift.modified:
            b, a = m["before"], m["after"]
            click.echo(click.style(
                f"    ~ {b.get('type', '?'):6s} {b.get('name', '?')}:  "
                f"{b.get('content', '')} → {a.get('content', '')}",
                fg="yellow",
            ))
    if drift.removed:
        click.echo("  Removed remotely:")
        for r in drift.removed:
            click.echo(click.style(f"    - {_fmt_record(r)}", fg="red"))


def _print_plan(plan) -> None:
    """Print a Plan's actions to stdout."""
    for a in plan.actions:
        prot = " [PROTECTED]" if a.protected else ""
        if a.action == "create":
            click.echo(click.style(f"  + CREATE {_fmt_record(a.record)}{prot}", fg="green"))
        elif a.action == "update":
            before_content = (a.before or {}).get("content", "?")
            click.echo(click.style(
                f"  ~ UPDATE {a.record.get('type', '?'):6s} {a.record.get('name', '?')}:  "
                f"{before_content} → {a.record.get('content', '')}{prot}",
                fg="yellow",
            ))
        elif a.action == "delete":
            click.echo(click.style(f"  - DELETE {_fmt_record(a.record)}{prot}", fg="red"))


# ======================================================================
# diff
# ======================================================================

@cli.command("diff")
@click.option("--zone", "-z", default=None, help="Zone name.  Omit for default / all.")
def diff_cmd(zone: str | None) -> None:
    """Show drift between local state and Cloudflare."""
    token = _require_token()
    for z in _resolve_zones(zone):
        drift = _engine.detect_drift(z, token)
        if drift is None:
            click.echo(f"{z}: Not synced yet.")
            continue
        if not drift.has_changes:
            click.echo(f"{z}: Clean (no drift)")
        else:
            click.echo(f"{z}: Drift detected — {drift.summary}")
            _print_diff(drift)


# ======================================================================
# plan
# ======================================================================

@cli.command("plan")
@click.option("--zone", "-z", default=None, help="Zone name.  Omit for default / all.")
def plan_cmd(zone: str | None) -> None:
    """Show planned changes (what would be applied to Cloudflare)."""
    token = _require_token()
    for z in _resolve_zones(zone):
        plan = _engine.generate_plan(z, token)
        if not plan.has_changes:
            msg = f"{z}: No changes to apply."
            if plan.drift and plan.drift.has_changes:
                msg += f"  (Drift detected: {plan.drift.summary} — run 'dnscli sync' to accept)"
            click.echo(msg)
        else:
            click.echo(f"{z}: {plan.summary}")
            _print_plan(plan)
            if plan.has_protected:
                n = sum(1 for a in plan.actions if a.protected)
                click.echo(click.style(
                    f"  ⚠ {n} protected record(s) will be skipped without --force",
                    fg="yellow",
                ))


# ======================================================================
# apply
# ======================================================================

@cli.command("apply")
@click.option("--zone", "-z", default=None, help="Zone name.  Omit for default / all.")
@click.option("--force", is_flag=True, help="Override protected-record guards.")
@click.confirmation_option(prompt="Apply changes to Cloudflare?")
def apply_cmd(zone: str | None, force: bool) -> None:
    """Apply planned changes to Cloudflare."""
    token = _require_token()
    for z in _resolve_zones(zone):
        plan = _engine.generate_plan(z, token)
        if not plan.has_changes:
            click.echo(f"{z}: No changes to apply.")
            continue
        click.echo(f"{z}: Applying {plan.summary} …")
        result = _engine.apply_plan(plan, token, force=force)
        if result.all_succeeded:
            click.echo(f"  ✓ Applied {len(result.succeeded)} change(s).")
        else:
            click.echo(f"  {len(result.succeeded)} succeeded, {len(result.failed)} failed:")
            for action, err in result.failed:
                click.echo(click.style(
                    f"    ✗ {action.action} {action.record.get('type')} "
                    f"{action.record.get('name')}: {err}",
                    fg="red",
                ))


# ======================================================================
# add
# ======================================================================

def _resolve_single_zone(zone: str | None) -> str:
    """Return exactly one zone name or abort."""
    zones = _resolve_zones(zone)
    if len(zones) != 1:
        click.echo("Multiple zones found. Specify --zone.", err=True)
        raise SystemExit(1)
    return zones[0]


@cli.command("add")
@click.option("--zone", "-z", default=None, help="Zone name.")
@click.option("--type", "rtype", required=True, type=click.Choice(["A", "AAAA", "CNAME", "MX", "TXT", "SRV"]), help="Record type.")
@click.option("--name", "rname", required=True, help="Record name (e.g. sub.example.com).")
@click.option("--content", required=True, help="Record content (IP, hostname, text value).")
@click.option("--ttl", default=1, type=int, help="TTL (1 = Auto).")
@click.option("--priority", default=10, type=int, help="Priority (MX/SRV only).")
@click.option("--proxied", is_flag=True, help="Enable Cloudflare proxy (A/AAAA/CNAME).")
def add_cmd(zone: str | None, rtype: str, rname: str, content: str,
            ttl: int, priority: int, proxied: bool) -> None:
    """Add a new DNS record to local state."""
    zone_name = _resolve_single_zone(zone)
    state = load_zone(zone_name)
    if state is None:
        click.echo(f"Zone '{zone_name}' not synced. Run 'dnscli sync' first.", err=True)
        raise SystemExit(1)

    # Auto-append zone name if bare subdomain
    if rname and not rname.endswith(zone_name):
        if "." not in rname or not rname.endswith("."):
            rname = f"{rname}.{zone_name}"

    record: dict = {"type": rtype, "name": rname, "content": content, "ttl": ttl, "proxied": proxied}
    if rtype in ("MX", "SRV"):
        record["priority"] = priority

    err = validate_record(record)
    if err:
        click.echo(f"Validation error: {err}", err=True)
        raise SystemExit(1)

    records = state["records"]
    records.append(record)
    save_zone(state["zone_id"], zone_name, records)
    _git.auto_init()
    _git.commit(f"Add {rtype} {rname}")
    click.echo(f"Added {rtype} {rname} → {content}")
    click.echo("Run 'dnscli plan' to review, then 'dnscli apply' to push to Cloudflare.")


# ======================================================================
# edit
# ======================================================================

@cli.command("edit")
@click.option("--zone", "-z", default=None, help="Zone name.")
@click.option("--name", "rname", required=True, help="Name of the record to edit.")
@click.option("--type", "rtype", required=True, type=click.Choice(["A", "AAAA", "CNAME", "MX", "TXT", "SRV"]), help="Record type.")
@click.option("--content", default=None, help="New content value.")
@click.option("--ttl", default=None, type=int, help="New TTL.")
@click.option("--priority", default=None, type=int, help="New priority (MX/SRV).")
@click.option("--proxied/--no-proxied", default=None, help="Cloudflare proxy toggle.")
def edit_cmd(zone: str | None, rname: str, rtype: str, content: str | None,
             ttl: int | None, priority: int | None, proxied: bool | None) -> None:
    """Edit an existing DNS record in local state."""
    zone_name = _resolve_single_zone(zone)
    state = load_zone(zone_name)
    if state is None:
        click.echo(f"Zone '{zone_name}' not synced.", err=True)
        raise SystemExit(1)

    # Find matching record
    matches = [r for r in state["records"]
               if r.get("type") == rtype and r.get("name") == rname]
    if not matches:
        click.echo(f"No {rtype} record named '{rname}' found.", err=True)
        raise SystemExit(1)
    if len(matches) > 1:
        click.echo(f"Multiple {rtype} records named '{rname}'. Edit in GUI for disambiguation.", err=True)
        raise SystemExit(1)

    rec = matches[0]
    if content is not None:
        rec["content"] = content
    if ttl is not None:
        rec["ttl"] = ttl
    if priority is not None:
        rec["priority"] = priority
    if proxied is not None:
        rec["proxied"] = proxied

    err = validate_record(rec)
    if err:
        click.echo(f"Validation error: {err}", err=True)
        raise SystemExit(1)

    save_zone(state["zone_id"], zone_name, state["records"])
    _git.auto_init()
    _git.commit(f"Edit {rtype} {rname}")
    click.echo(f"Updated {rtype} {rname}")
    click.echo("Run 'dnscli plan' to review, then 'dnscli apply' to push to Cloudflare.")


# ======================================================================
# delete (record)
# ======================================================================

@cli.command("rm")
@click.option("--zone", "-z", default=None, help="Zone name.")
@click.option("--name", "rname", required=True, help="Record name to delete.")
@click.option("--type", "rtype", required=True, type=click.Choice(["A", "AAAA", "CNAME", "MX", "TXT", "SRV"]), help="Record type.")
@click.confirmation_option(prompt="Delete this record from local state?")
def rm_cmd(zone: str | None, rname: str, rtype: str) -> None:
    """Remove a DNS record from local state."""
    zone_name = _resolve_single_zone(zone)
    state = load_zone(zone_name)
    if state is None:
        click.echo(f"Zone '{zone_name}' not synced.", err=True)
        raise SystemExit(1)

    before = len(state["records"])
    state["records"] = [r for r in state["records"]
                        if not (r.get("type") == rtype and r.get("name") == rname)]
    after = len(state["records"])

    if before == after:
        click.echo(f"No {rtype} record named '{rname}' found.", err=True)
        raise SystemExit(1)

    save_zone(state["zone_id"], zone_name, state["records"])
    _git.auto_init()
    _git.commit(f"Delete {rtype} {rname}")
    removed = before - after
    click.echo(f"Removed {removed} record(s): {rtype} {rname}")
    click.echo("Run 'dnscli plan' to review, then 'dnscli apply' to push to Cloudflare.")


# ======================================================================
# rollback
# ======================================================================

@cli.command("rollback")
@click.argument("commit")
def rollback_cmd(commit: str) -> None:
    """Rollback state to a previous git commit."""
    _require_token()
    _git.auto_init()

    history = _git.log()
    if not history:
        click.echo("No git history found. Nothing to roll back to.", err=True)
        raise SystemExit(1)

    # Validate the commit exists in our history
    known_shas = {c["sha"] for c in history} | {c["short_sha"] for c in history}
    if commit not in known_shas:
        click.echo(f"Commit '{commit}' not found in dnsctl history.", err=True)
        click.echo("Use 'dnscli log' to see available commits.")
        raise SystemExit(1)

    try:
        new_sha = _git.rollback(commit)
        click.echo(f"Rolled back to {commit}")
        click.echo(f"New commit: {new_sha[:8]}")
        click.echo("Run 'dnscli plan' to review, then 'dnscli apply' to push to Cloudflare.")
    except ValueError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)


# ======================================================================
# log
# ======================================================================

@cli.command("log")
@click.option("--count", "-n", default=20, type=int, help="Number of commits to show.")
def log_cmd(count: int) -> None:
    """Show git commit history for the state directory."""
    _git.auto_init()
    history = _git.log(max_count=count)
    if not history:
        click.echo("No history yet.")
        return
    for entry in history:
        click.echo(
            f"{entry['short_sha']}  {entry['date'][:19]}  {entry['message']}"
        )


# ======================================================================
# export
# ======================================================================

@cli.command("export")
@click.option("--zone", "-z", default=None, help="Zone name to export.")
@click.option("--output", "-o", "outfile", default=None, type=click.Path(), help="Output file path.")
def export_cmd(zone: str | None, outfile: str | None) -> None:
    """Export a zone's state to a JSON file."""
    from pathlib import Path

    zone_name = _resolve_single_zone(zone)

    if outfile is None:
        outfile = f"{zone_name}.export.json"
    dest = Path(outfile)

    try:
        export_zone(zone_name, dest)
        click.echo(f"Exported {zone_name} → {dest}")
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)


# ======================================================================
# import
# ======================================================================

@cli.command("import")
@click.argument("file", type=click.Path(exists=True))
def import_cmd(file: str) -> None:
    """Import zone state from a JSON file."""
    from pathlib import Path

    init_state_dir()
    src = Path(file)

    try:
        state = import_zone(src)
        zone_name = state["zone_name"]
        n = len(state.get("records", []))
        click.echo(f"Imported {zone_name} ({n} records)")

        _git.auto_init()
        sha = _git.commit(f"Imported state for {zone_name}")
        if sha:
            click.echo(f"Committed: {sha[:8]}")
    except ValueError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)


# ======================================================================
# protect / unprotect / protected
# ======================================================================

@cli.command("protect")
@click.option("--type", "rtype", required=True, type=click.Choice(["A", "AAAA", "CNAME", "MX", "TXT", "SRV"]), help="Record type.")
@click.option("--name", "rname", required=True, help="Record name.")
@click.option("--reason", default="", help="Reason for protection.")
def protect_cmd(rtype: str, rname: str, reason: str) -> None:
    """Mark a record as protected (requires --force to modify)."""
    add_protected_record(rtype, rname, reason)
    click.echo(f"Protected: {rtype} {rname}")


@cli.command("unprotect")
@click.option("--type", "rtype", required=True, type=click.Choice(["A", "AAAA", "CNAME", "MX", "TXT", "SRV"]), help="Record type.")
@click.option("--name", "rname", required=True, help="Record name.")
def unprotect_cmd(rtype: str, rname: str) -> None:
    """Remove protection from a record."""
    remove_protected_record(rtype, rname)
    click.echo(f"Unprotected: {rtype} {rname}")


@cli.command("protected")
def protected_cmd() -> None:
    """List all protected records."""
    protected = load_protected_records()
    if not protected:
        click.echo("No user-defined protected records.")
        click.echo("(NS records are always system-protected.)")
        return
    click.echo(f"Protected records ({len(protected)}):")
    for p in protected:
        reason = f"  — {p['reason']}" if p.get('reason') else ""
        click.echo(f"  {p['type']:6s} {p['name']}{reason}")
    click.echo("\n(NS records are always system-protected.)")


# ======================================================================
# status
# ======================================================================

@cli.command()
def status() -> None:
    """Show current dnsctl status."""
    click.echo(f"State directory: {STATE_DIR}")
    click.echo(f"Logged in: {is_logged_in()}")
    click.echo(f"Session active: {get_token() is not None}")

    synced = list_synced_zones()
    if synced:
        click.echo(f"Synced zones ({len(synced)}):")
        for name in synced:
            state = load_zone(name)
            if state:
                n = len(state.get("records", []))
                ts = state.get("last_synced_at", "?")
                click.echo(f"  {name}  ({n} records, last sync: {ts})")
    else:
        click.echo("No zones synced yet.  Run 'dnscli sync'.")

    cfg = get_config()
    default = cfg.get("default_zone")
    if default:
        click.echo(f"Default zone: {default}")


# ======================================================================
# lock (convenience)
# ======================================================================

@cli.command("lock")
def lock_cmd() -> None:
    """Lock the current session (clear cached token)."""
    lock()
    click.echo("Session locked.")





# ======================================================================
# logout
# ======================================================================

@cli.command("logout")
def logout_cmd() -> None:
    """Remove all stored credentials."""
    logout()
    click.echo("Logged out.  All stored credentials removed.")



# ======================================================================
# Entry point
# ======================================================================

if __name__ == "__main__":
    cli()
