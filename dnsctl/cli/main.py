"""dnsctl — Click-based CLI entry point."""

import getpass
import logging
import sys

import click

from dnsctl.config import ACCOUNTS_DIR, LOG_FILE, STATE_DIR
from dnsctl.core.cloudflare_client import CloudflareClient, sanitize_token
from dnsctl.core.git_manager import GitManager
from dnsctl.core.security import get_token, is_logged_in, lock, login, logout, unlock
from dnsctl.core.state_manager import (
    add_account,
    add_protected_record,
    export_zone,
    get_config,
    get_current_account,
    import_zone,
    init_state_dir,
    list_accounts,
    list_synced_zones,
    load_protected_records,
    load_zone,
    remove_account,
    remove_protected_record,
    save_zone,
    set_config,
    set_current_account,
    slugify,
)
from dnsctl.core.sync_engine import SyncEngine
from dnsctl.core.validations import validate_record

logger = logging.getLogger("dnsctl")
_cf = CloudflareClient()


def _get_alias() -> str:
    """Return the current account alias (falls back to 'default')."""
    return get_current_account() or "default"


def _get_git() -> GitManager:
    """Return a GitManager for the current account."""
    return GitManager(ACCOUNTS_DIR / _get_alias())


def _get_engine() -> SyncEngine:
    """Return a SyncEngine for the current account."""
    return SyncEngine(alias=_get_alias())


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
    token = get_token(_get_alias())
    if token is None:
        click.echo("Session locked or expired.  Run 'dnsctl unlock' first.", err=True)
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
    _get_git().auto_init()
    click.echo(f"Initialised dnsctl state in {path}")


# ======================================================================
# login
# ======================================================================

@cli.command("login")
@click.option("--label", "-l", default=None, help="Human-readable account name (e.g. 'Personal', 'Work').")
@click.option("--alias", "-a", "acct_alias", default=None, help="Short unique identifier (auto-derived from label if omitted).")
def login_cmd(label: str | None, acct_alias: str | None) -> None:
    """Store a Cloudflare API token (encrypted with a master password)."""
    if not label:
        label = click.prompt("Account name (e.g. Personal, Work, Client A)")
    if not label.strip():
        click.echo("Account name cannot be empty.", err=True)
        raise SystemExit(1)

    if not acct_alias:
        existing_aliases = {a["alias"] for a in list_accounts()}
        base = slugify(label)
        acct_alias = base
        counter = 1
        while acct_alias in existing_aliases:
            acct_alias = f"{base}_{counter}"
            counter += 1

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

    init_state_dir()
    add_account(acct_alias, label)
    login(token, password, acct_alias)
    set_current_account(acct_alias)
    git = GitManager(ACCOUNTS_DIR / acct_alias)
    git.auto_init()
    click.echo(f"Account \u2018{label}\u2019 ({acct_alias}) stored.  Run 'dnsctl unlock' to start a session.")





# ======================================================================
# unlock
# ======================================================================

@cli.command("unlock")
@click.option("--account", "-a", default=None, help="Account alias to unlock.  Defaults to current account.")
def unlock_cmd(account: str | None) -> None:
    """Unlock the session by entering the master password."""
    alias = account or _get_alias()
    if not is_logged_in(alias):
        click.echo(f"No stored token for account \u2018{alias}\u2019.  Run 'dnsctl login' first.", err=True)
        raise SystemExit(1)
    password = getpass.getpass("Master password: ")
    try:
        unlock(password, alias)
    except Exception:
        click.echo("Wrong password or corrupted token.", err=True)
        raise SystemExit(1)
    click.echo(f"Session unlocked for account \u2018{alias}\u2019.")
    from dnsctl.core.security import unlock_all
    other_aliases = [a["alias"] for a in list_accounts() if a["alias"] != alias]
    unlocked = unlock_all(password, other_aliases)
    if unlocked:
        names = ", ".join(f"\u2018{a}\u2019" for a in unlocked)
        click.echo(f"Also unlocked: {names}")



# ======================================================================
# sync
# ======================================================================

@cli.command()
@click.option("--zone", "-z", default=None, help="Zone name to sync.  Omit to sync all.")
def sync(zone: str | None) -> None:
    """Sync DNS records from Cloudflare to local state."""
    init_state_dir()
    token = _require_token()
    alias = _get_alias()
    git = _get_git()

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

    git.auto_init()

    for z in targets:
        records = _cf.list_records(token, z["id"])
        state = save_zone(z["id"], z["name"], records, alias)
        click.echo(f"  Synced {z['name']}  ({len(records)} records, hash={state['state_hash'][:12]})")

    sha = git.commit(f"Sync with remote ({len(targets)} zone(s))")
    if sha:
        click.echo(f"Committed: {sha[:8]}")

    # Set default zone for this account if not set
    cfg = get_config()
    default_key = f"default_zone_{alias}"
    if cfg.get(default_key) is None and targets:
        set_config(default_key, targets[0]["name"])


# ======================================================================
# Helpers for diff / plan output
# ======================================================================

def _resolve_zones(zone: str | None, alias: str) -> list[str]:
    """Resolve a zone argument to a list of zone names."""
    if zone:
        return [zone]
    cfg = get_config()
    default = cfg.get(f"default_zone_{alias}")
    if default:
        return [default]
    synced = list_synced_zones(alias)
    if not synced:
        click.echo("No zones synced. Run 'dnsctl sync' first.", err=True)
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
    alias = _get_alias()
    engine = _get_engine()
    for z in _resolve_zones(zone, alias):
        drift = engine.detect_drift(z, token)
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
    alias = _get_alias()
    engine = _get_engine()
    for z in _resolve_zones(zone, alias):
        plan = engine.generate_plan(z, token)
        if not plan.has_changes:
            msg = f"{z}: No changes to apply."
            if plan.drift and plan.drift.has_changes:
                msg += f"  (Drift detected: {plan.drift.summary} — run 'dnsctl sync' to accept)"
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
    alias = _get_alias()
    engine = _get_engine()
    for z in _resolve_zones(zone, alias):
        plan = engine.generate_plan(z, token)
        if not plan.has_changes:
            click.echo(f"{z}: No changes to apply.")
            continue
        click.echo(f"{z}: Applying {plan.summary} …")
        result = engine.apply_plan(plan, token, force=force)
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
        if result.sync_failed:
            click.echo(click.style(
                "  ⚠ Post-apply sync failed — local state may be stale. Run 'dnsctl sync'.",
                fg="yellow",
            ))


# ======================================================================
# add
# ======================================================================

def _resolve_single_zone(zone: str | None, alias: str) -> str:
    """Return exactly one zone name or abort."""
    zones = _resolve_zones(zone, alias)
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
    alias = _get_alias()
    zone_name = _resolve_single_zone(zone, alias)
    state = load_zone(zone_name, alias)
    if state is None:
        click.echo(f"Zone '{zone_name}' not synced. Run 'dnsctl sync' first.", err=True)
        raise SystemExit(1)

    # Auto-append zone name if bare subdomain; warn for ambiguous multi-dot names
    if rname and not rname.endswith(zone_name) and not rname.endswith("."):
        if "." not in rname:
            rname = f"{rname}.{zone_name}"
        else:
            proposed = f"{rname}.{zone_name}"
            click.echo(
                f"Warning: '{rname}' doesn't end with the zone '{zone_name}'.",
                err=True,
            )
            if click.confirm(f"Append zone to make it '{proposed}'?", default=True):
                rname = proposed

    record: dict = {"type": rtype, "name": rname, "content": content, "ttl": ttl, "proxied": proxied}
    if rtype in ("MX", "SRV"):
        record["priority"] = priority

    err = validate_record(record)
    if err:
        click.echo(f"Validation error: {err}", err=True)
        raise SystemExit(1)

    records = state["records"]
    records.append(record)
    save_zone(state["zone_id"], zone_name, records, alias)
    git = _get_git()
    git.auto_init()
    git.commit(f"Add {rtype} {rname}")
    click.echo(f"Added {rtype} {rname} → {content}")
    click.echo("Run 'dnsctl plan' to review, then 'dnsctl apply' to push to Cloudflare.")


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
    alias = _get_alias()
    zone_name = _resolve_single_zone(zone, alias)
    state = load_zone(zone_name, alias)
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

    save_zone(state["zone_id"], zone_name, state["records"], alias)
    git = _get_git()
    git.auto_init()
    git.commit(f"Edit {rtype} {rname}")
    click.echo(f"Updated {rtype} {rname}")
    click.echo("Run 'dnsctl plan' to review, then 'dnsctl apply' to push to Cloudflare.")


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
    alias = _get_alias()
    zone_name = _resolve_single_zone(zone, alias)
    state = load_zone(zone_name, alias)
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

    save_zone(state["zone_id"], zone_name, state["records"], alias)
    git = _get_git()
    git.auto_init()
    git.commit(f"Delete {rtype} {rname}")
    removed = before - after
    click.echo(f"Removed {removed} record(s): {rtype} {rname}")
    click.echo("Run 'dnsctl plan' to review, then 'dnsctl apply' to push to Cloudflare.")


# ======================================================================
# rollback
# ======================================================================

@cli.command("rollback")
@click.argument("commit")
def rollback_cmd(commit: str) -> None:
    """Rollback state to a previous git commit."""
    _require_token()
    git = _get_git()
    git.auto_init()

    history = git.log()
    if not history:
        click.echo("No git history found. Nothing to roll back to.", err=True)
        raise SystemExit(1)

    # Validate the commit exists in our history
    known_shas = {c["sha"] for c in history} | {c["short_sha"] for c in history}
    if commit not in known_shas:
        click.echo(f"Commit '{commit}' not found in dnsctl history.", err=True)
        click.echo("Use 'dnsctl log' to see available commits.")
        raise SystemExit(1)

    try:
        new_sha = git.rollback(commit)
        click.echo(f"Rolled back to {commit}")
        click.echo(f"New commit: {new_sha[:8]}")
        click.echo("Run 'dnsctl plan' to review, then 'dnsctl apply' to push to Cloudflare.")
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
    git = _get_git()
    git.auto_init()
    history = git.log(max_count=count)
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
        export_zone(zone_name, dest, _get_alias())
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
    alias = _get_alias()

    try:
        state = import_zone(src, alias)
        zone_name = state["zone_name"]
        n = len(state.get("records", []))
        click.echo(f"Imported {zone_name} ({n} records)")

        git = _get_git()
        git.auto_init()
        sha = git.commit(f"Imported state for {zone_name}")
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
    alias = _get_alias()
    click.echo(f"State directory: {STATE_DIR}")

    # Show all accounts
    accounts = list_accounts()
    if accounts:
        click.echo(f"Accounts ({len(accounts)}):")
        for a in accounts:
            marker = "*" if a["alias"] == alias else " "
            logged = is_logged_in(a["alias"])
            session = get_token(a["alias"]) is not None
            click.echo(f"  {marker} {a['alias']}  ({a['label']})  logged_in={logged}  session={session}")
    else:
        click.echo(f"Current account: {alias}")
        click.echo(f"Logged in: {is_logged_in(alias)}")
        click.echo(f"Session active: {get_token(alias) is not None}")

    synced = list_synced_zones(alias)
    if synced:
        click.echo(f"Synced zones ({len(synced)}):")
        for name in synced:
            state = load_zone(name, alias)
            if state:
                n = len(state.get("records", []))
                ts = state.get("last_synced_at", "?")
                click.echo(f"  {name}  ({n} records, last sync: {ts})")
    else:
        click.echo("No zones synced yet.  Run 'dnsctl sync'.")

    cfg = get_config()
    default = cfg.get(f"default_zone_{alias}")
    if default:
        click.echo(f"Default zone: {default}")


# ======================================================================
# lock (convenience)
# ======================================================================

@cli.command("lock")
def lock_cmd() -> None:
    """Lock the current session (clear cached token)."""
    lock(_get_alias())
    click.echo("Session locked.")





# ======================================================================
# logout
# ======================================================================

@cli.command("logout")
def logout_cmd() -> None:
    """Remove all stored credentials for the current account."""
    alias = _get_alias()
    logout(alias)
    click.echo(f"Logged out account \u2018{alias}\u2019.  All stored credentials removed.")



# ======================================================================
# accounts group
# ======================================================================

@cli.group("accounts")
def accounts_group() -> None:
    """Manage multiple Cloudflare accounts."""


@accounts_group.command("list")
def accounts_list_cmd() -> None:
    """List all stored accounts."""
    accounts = list_accounts()
    current = _get_alias()
    if not accounts:
        click.echo("No accounts.  Run 'dnsctl login' to add one.")
        return
    for a in accounts:
        marker = "*" if a["alias"] == current else " "
        click.echo(f"  {marker} {a['alias']}  ({a['label']})")


@accounts_group.command("switch")
@click.argument("alias")
def accounts_switch_cmd(alias: str) -> None:
    """Switch the active account."""
    known = {a["alias"] for a in list_accounts()}
    if alias not in known:
        click.echo(f"Account '{alias}' not found.", err=True)
        raise SystemExit(1)
    set_current_account(alias)
    click.echo(f"Switched to account \u2018{alias}\u2019.")


@accounts_group.command("remove")
@click.argument("alias")
@click.confirmation_option(prompt="Remove this account? All local zone data will be deleted.")
def accounts_remove_cmd(alias: str) -> None:
    """Remove a stored account and all its local zone data."""
    from dnsctl.core.security import logout as sec_logout

    accounts = list_accounts()
    if len(accounts) <= 1:
        click.echo("Cannot remove the last account.", err=True)
        raise SystemExit(1)
    known = {a["alias"] for a in accounts}
    if alias not in known:
        click.echo(f"Account '{alias}' not found.", err=True)
        raise SystemExit(1)

    sec_logout(alias)
    remove_account(alias)
    click.echo(f"Removed account \u2018{alias}\u2019.")

    # Auto-switch if this was the current account
    if get_current_account() == alias:
        remaining = list_accounts()
        if remaining:
            set_current_account(remaining[0]["alias"])
            click.echo(f"Switched to account \u2018{remaining[0]['alias']}\u2019.")


# ======================================================================
# Entry point
# ======================================================================

def main() -> None:
    """Entry point wrapper — catches Ctrl+C for a clean exit."""
    try:
        cli(standalone_mode=True)
    except KeyboardInterrupt:
        click.echo("\nAborted.", err=True)
        sys.exit(130)


if __name__ == "__main__":
    main()
