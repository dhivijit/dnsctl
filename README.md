# DNSCTL

**Secure, version-controlled DNS management for Cloudflare (CLI + GUI)**

DNSCTL is a local infrastructure tool for safely managing Cloudflare DNS records using a Git-backed state model, drift detection, and a plan/apply workflow.

It combines:

- A powerful CLI for automation
- A PyQt GUI for visualization
- Secure secret handling
- Version-controlled state
- Protected record enforcement

Think of it as a lightweight, DNS-focused reconciliation engine for Cloudflare.

---

## ✨ Key Features

- **State Sync** — Pull DNS records into local JSON state
- **Local Editing** — Add / edit / delete records safely
- **Drift Detection** — Detect out-of-band dashboard changes
- **Plan / Apply Workflow** — Preview before pushing
- **Protected Records** — System + user-defined protection
- **Git-Backed History** — Every state change auto-committed
- **Secure Token Storage** — AES-GCM encrypted + OS keyring
- **Session Locking** — Auto-expires after inactivity
- **CLI + GUI Parity** — Same core engine

---

## 📦 Installation

### Requirements

- Python 3.11+
- Git installed
- OS keyring support (Windows Credential Manager / macOS Keychain / Linux Secret Service)

### Install from Source

```bash
git clone https://github.com/dhivijit/dnsctl
cd dnsctl
pip install .
```

For development mode:

```bash
pip install -e .
```

This provides:

- `dnsctl` — CLI interface  
- `dnsctl-g` — GUI launcher  

---

## 🚀 Quick Start

### 1. Initialize local state

```bash
dnsctl init
```

### 2. Store your Cloudflare API token (encrypted)

```bash
dnsctl login
```

The token is:
- Encrypted with AES-256-GCM
- Key derived via PBKDF2 (200k iterations)
- Stored securely in OS keyring

### 3. Unlock session

```bash
dnsctl unlock
```

### 4. Sync zones

```bash
dnsctl sync
```

---

## 🧰 CLI Overview

### Authentication

```bash
dnsctl init
dnsctl login
dnsctl unlock
dnsctl lock
dnsctl logout
```

### Sync & Status

```bash
dnsctl sync [-z ZONE]
dnsctl status
dnsctl diff
dnsctl plan
dnsctl apply
```

### Record Management (Local State)

```bash
dnsctl add --type A --name sub.example.com --content 1.2.3.4
dnsctl edit --type A --name sub.example.com --content 5.6.7.8
dnsctl rm --type A --name sub.example.com
```

### Protected Records

```bash
dnsctl protect --type A --name example.com --reason "Critical root record"
dnsctl unprotect --type A --name example.com
dnsctl protected
```

### History & Rollback

```bash
dnsctl log
dnsctl rollback <commit_sha>
```

### Import / Export

```bash
dnsctl export
dnsctl import zone.json
```

---

## 🖥 GUI

Launch:

```bash
dnsctl-g
```

Features:

- Zone selector
- Record type tabs (A, CNAME, MX, TXT, etc.)
- Drift status indicator
- Sync / Plan / Apply controls
- Record add/edit/delete dialogs
- History & rollback viewer
- Session unlock modal

The GUI uses the same reconciliation engine as the CLI.

---

## 🔐 Security Model

DNSCTL is designed for secure local infrastructure management.

### Token Handling

- API token is never stored in plaintext
- Encrypted with AES-GCM
- Derived from master password using PBKDF2-HMAC-SHA256
- Encrypted blob stored in OS keyring
- Session auto-expires (default: 15 minutes)

### Protected Records

Two layers of protection:

1. System-level (e.g., NS records)
2. User-defined protection flags

Protected records require explicit force to modify or delete.

---

## 🧠 Design Philosophy

DNSCTL is built around:

- Explicit change control
- Safe reconciliation
- Drift awareness
- Secure secret handling
- Recoverable state

It is intended for developers and security engineers who want more control than a web dashboard provides.

---

## ⚠️ Scope

DNSCTL is:

- A local DNS management tool
- Designed for single-user environments
- Focused on Cloudflare DNS

It is not:

- A multi-user SaaS system
- A remote secret manager
- A full Terraform replacement

---

## 📜 License

MIT License  
© Dhivijit