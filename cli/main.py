"""dnscli — Click-based CLI entry point."""

import getpass
import logging
import sys

import click

from config import STATE_DIR
from core.cloudflare_client import CloudflareClient, sanitize_token
from core.git_manager import GitManager
from core.security import get_token, is_logged_in, lock, login, logout, unlock
from core.state_manager import (
    get_config,
    init_state_dir,
    list_synced_zones,
    load_zone,
    save_zone,
    set_config,
)

logger = logging.getLogger("dnsctl")
_cf = CloudflareClient()
_git = GitManager()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
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
