---
name: operate-virtuoso-bridge
description: Connect Codex to Cadence Virtuoso through virtuoso-bridge-lite and operate the active CIW session with CLI, Python, or SKILL. Use for bridge setup or recovery, status checks, window and cellview inspection, schematic/layout/library/symbol/Maestro operations, screenshots, loading .il files, and troubleshooting SSH tunnels or the Virtuoso daemon. Also use when the user asks Codex or an AI agent to inspect or change a Virtuoso design.
---

# Operate Virtuoso Bridge

Operate Virtuoso through the installed bridge. Treat the active Virtuoso session and design database as live user state.

## Start every task

1. Locate the `virtuoso-bridge-lite` checkout containing `.env` and `.venv`. Prefer the current workspace; otherwise read [references/environment.md](references/environment.md).
2. On Windows, call `.\.venv\Scripts\virtuoso-bridge.exe` directly. Do not depend on `Activate.ps1`; PowerShell execution policy may block it.
3. Run `status` before any Virtuoso operation.
4. If `[daemon] OK`, continue. If not, follow **Recover connectivity**.
5. For an ambiguous request, inspect first with `windows`, `snapshot`, or read-only SKILL. Do not guess the active library/cell/view.

## Choose the interface

- Use CLI `eval` for short SKILL expressions and diagnostics.
- Use CLI `load FILE.il` for reviewed multi-form SKILL files.
- Use Python `VirtuosoClient.from_env()` for structured results, loops, file transfers, and multi-step workflows.
- Prefer `client.layout`, `client.schematic`, `client.library`, `client.symbol`, and `client.maestro` for supported domain operations.
- Use `SpectreSimulator` only when `status` reports Spectre available. Virtuoso daemon and Spectre are independent.

Read [references/operations.md](references/operations.md) for commands, quoting rules, recovery, and Python examples.

## Safety rules

- Default to read-only inspection unless the user clearly requests a change.
- Before editing, resolve the exact library, cell, view, mode, and intended save behavior.
- Prefer creating or modifying an explicit target cellview; never assume the frontmost window is the intended target for destructive changes.
- Read current parameters or geometry before changing them, then reread after saving to verify the result.
- Use the bridge for SKILL execution. Do not SSH into the VM and attempt to run SKILL from a shell.
- Treat `RBStop`, `RBStopAll`, tunnel restarts, overwrites, deletes, and replacements as state-changing recovery actions. Use them only when required and scoped.
- Keep the daemon behind the SSH tunnel. Do not expose its TCP port to untrusted networks.
- Remote paths belong to the VM. Transfer required inputs and outputs explicitly through bridge upload/download APIs.
- Report the executed target, result, and verification. Surface SKILL errors verbatim enough to diagnose them.

## Read-only orientation

Run these in order when the user asks what is open or requests an operation without a precise target:

```powershell
.\.venv\Scripts\virtuoso-bridge.exe status
.\.venv\Scripts\virtuoso-bridge.exe windows
.\.venv\Scripts\virtuoso-bridge.exe snapshot
```

To read the active cellview without modifying it:

```powershell
.\.venv\Scripts\virtuoso-bridge.exe eval 'let((cv) cv=geGetEditCellView() if(cv list(cv~>libName cv~>cellName cv~>viewName) nil))'
```

## Recover connectivity

Follow the least disruptive sequence:

1. Confirm the VM is running and its configured IP is still valid.
2. Confirm passwordless SSH with `ssh -o BatchMode=yes user@host "hostname; whoami"`.
3. Run `virtuoso-bridge start` if the tunnel is down.
4. If the tunnel works but the daemon has no response, present the exact `load(".../virtuoso_setup.il")` line printed by `status` and ask the user to run it in the Virtuoso CIW.
5. If CIW reports an existing daemon, use `RBStop()` first; use `RBStopAll()` only if the stale daemon cannot otherwise be cleared, then reload the generated setup file.
6. Run `status`, then execute `eval "1+2"`; require success with output `3` before design work.

Do not claim the bridge is ready merely because the SSH tunnel is running; `[daemon] OK` and a successful SKILL round trip are the readiness criteria.
