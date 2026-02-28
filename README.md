# DNSCTL

A secure, version-controlled DNS management tool for Cloudflare with both CLI and GUI interfaces.

DNSCTL works like a lightweight **Terraform for DNS** — you sync remote state, make local edits, preview a plan, and apply changes. Every mutation is tracked in a local git repository.

---

## Features

- **Sync** — Pull all DNS records from Cloudflare into local JSON state
- **CRUD** — Add, edit, and delete records locally before pushing
- **Drift Detection** — See what changed on Cloudflare since your last sync
- **Plan / Apply** — Preview exactly what will change, then apply with one command
- **Protected Records** — System-level (NS) and user-defined protections prevent accidental changes
- **Git-backed History** — Every sync and apply is auto-committed for full audit trail
- **Secure Token Storage** — API token encrypted with AES-256-GCM, key derived via PBKDF2 (200k iterations), stored in OS keyring
- **Session Timeout** — Auto-locks after 15 minutes of inactivity
- **Multi-zone** — Manage all zones accessible to your API token

---

## Architecture

```
             ┌──────────────────────┐
             │   Cloudflare API     │
             └───────────┬──────────┘
                         │
                         ▼
              ┌────────────────────┐
              │  Cloudflare Client │
              └───────────┬────────┘
                          │
                          ▼
              ┌────────────────────┐
              │    Sync Engine     │
              │  (Reconciliation)  │
              └───────────┬────────┘
                          │
     ┌────────────────────┼────────────────────┐
     ▼                    ▼                    ▼
┌──────────┐       ┌──────────────┐     ┌──────────────┐
│  Diff    │       │    State     │     │     Git      │
│  Engine  │       │   Manager    │     │   Manager    │
└──────────┘       └──────────────┘     └──────────────┘
                          │
                          ▼
                   ~/.dnsctl/zones/
```

CLI and GUI share the same core engine — no business logic in the UI layer.

---

## Installation

**Requirements:** Python 3.11+

```bash
pip install -r requirements.txt
```

### Dependencies

| Package        | Purpose                        |
|----------------|--------------------------------|
| `requests`     | Cloudflare API client          |
| `click`        | CLI framework                  |
| `PyQt6`        | GUI framework                  |
| `cryptography` | AES-256-GCM token encryption   |
| `keyring`      | OS keyring for credential storage |
| `GitPython`    | Auto-managed git repository    |

---

## Quick Start

```bash
# 1. Initialise the state directory
dnscli init

# 2. Store your Cloudflare API token (encrypted)
dnscli login

# 3. Unlock the session
dnscli unlock

# 4. Sync all zones from Cloudflare
dnscli sync

# 5. Check status
dnscli status
```

---

## CLI Reference

```
dnscli [--verbose] COMMAND
```

### Authentication

| Command           | Description                                  |
|-------------------|----------------------------------------------|
| `dnscli init`     | Create the `~/.dnsctl/` state directory      |
| `dnscli login`    | Store API token (encrypted with master password) |
| `dnscli unlock`   | Unlock the session with your master password |
| `dnscli lock`     | Lock the session (clear cached token)        |
| `dnscli logout`   | Remove all stored credentials                |

### Sync & Status

| Command                  | Description                              |
|--------------------------|------------------------------------------|
| `dnscli sync [-z ZONE]`  | Pull DNS records from Cloudflare         |
| `dnscli status`           | Show state directory, session, synced zones |

### Record Management

All record commands edit **local state only**. Nothing hits Cloudflare until you `apply`.

```bash
# Add a record
dnscli add --type A --name sub.example.com --content 1.2.3.4
dnscli add --type A --name sub --content 1.2.3.4 --proxied   # auto-appends zone
dnscli add --type MX --name example.com --content mail.example.com --priority 10

# Edit a record
dnscli edit --type A --name sub.example.com --content 5.6.7.8
dnscli edit --type A --name sub.example.com --ttl 3600

# Delete a record
dnscli rm --type A --name sub.example.com --yes
```

### Diff / Plan / Apply

```bash
# See what changed on Cloudflare since last sync
dnscli diff

# Preview what would be pushed to Cloudflare
dnscli plan

# Apply the plan
dnscli apply --yes

# Apply with protected-record override
dnscli apply --yes --force
```

---

## GUI

Launch the GUI:

```bash
dnscli-g
# or
python -m gui.app
```

### Main Window

- **Zone Selector** — Switch between all synced zones
- **Drift Badge** — Shows sync status: Clean (green), Drift (orange), Local changes (blue)
- **Record Tabs** — View records filtered by type: All, A, AAAA, CNAME, MX, TXT, SRV
- **Sync** — Pull latest state from Cloudflare
- **Plan** — Opens a dialog previewing all planned changes with a rich HTML diff
- **Lock** — Lock the session and close

### Record Editing

- **Add Record** — Opens a form to create a new record (type, name, content, TTL, priority, proxied)
- **Edit Record** — Select a row, click Edit to modify it
- **Delete Record** — Select a row, click Delete with confirmation

### Plan Preview Dialog

- Shows **drift** (remote changes since last sync) and **planned actions** (local → remote)
- Color-coded table: green = create, yellow = update, red = delete
- **Apply** button pushes changes to Cloudflare
- **Force Apply** button appears when protected records are involved
- After apply, state is re-synced and git-committed automatically

### Authentication Flow

- First launch → Login dialog (API token + master password)
- Subsequent launches → Unlock dialog (master password only)
- **Forgot Password** button clears all credentials and restarts login

---

## Security

- API token is **never** stored in plaintext, written to disk, or logged
- Encrypted with AES-256-GCM; key derived using PBKDF2-HMAC-SHA256 (200,000 iterations)
- Encrypted blob stored in OS keyring (Windows Credential Locker / macOS Keychain / Linux Secret Service)
- Session auto-expires after 15 minutes of inactivity
- Token input is sanitized — rejects pasted curl commands or Bearer headers

---

## State Directory

All state lives in `~/.dnsctl/` (override with `DNSCTL_STATE_DIR` env var):

```
~/.dnsctl/
├── .git/              # Auto-managed git repo
├── .gitignore         # Excludes session file and logs
├── zones/
│   └── example.com.json
├── metadata.json      # Protected records list
├── config.json        # Default zone, preferences
├── .session           # Session timestamp (gitignored)
└── logs/
    └── dnsctl.log
```

Each zone file:

```json
{
  "zone_id": "abc123",
  "zone_name": "example.com",
  "records": [...],
  "last_synced_at": "2026-02-28T12:00:00+00:00",
  "state_hash": "sha256..."
}
```

---

## Supported Record Types

A, AAAA, CNAME, MX, TXT, SRV

NS records are system-protected and filtered from management.

---

## Tech Stack

Python 3.11+ · PyQt6 · Click · requests · cryptography · keyring · GitPython
