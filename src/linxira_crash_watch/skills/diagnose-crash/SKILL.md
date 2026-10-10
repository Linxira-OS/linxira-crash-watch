---
name: diagnose-crash
description: "Diagnose a captured crash from a Linxira crash-watch debug workspace. Read the text-only evidence (crash event JSON, backtrace), reconstruct facts, judge whether it is worth escalating, and write the conclusion to notes.md. Use when asked to investigate a crash, work a crash-watch backlog batch, or explain a systemd-coredump entry."
skill_class: workflow
load_policy: conditional
risk_tags: []
---

# Crash diagnosis (crash-watch)

Linxira `crash-watch` captures crashes into a **text-only** debug workspace and
notifies the user. The agent is only woken on **explicit request** — nothing in
this flow wakes an agent on its own. This skill is the agent-side SOP for one
capture.

## Where the evidence is

The debug workspace (default `~/Linxira/debug`) is a git repo of text only:

```text
<ws>/
├── INDEX.md            # generated overview: pending / investigated
├── backlog.json        # pinned items with severity + reason
├── mute.json           # per-program mute list
└── batches/
    └── <date>-<slug>/
        ├── events/*.json    # org.linxira.crash-event.v1 records
        ├── backtrace.txt    # text evidence (no raw dump)
        ├── notes.md         # ← your conclusion goes here
        └── patch/
```

- Raw core dumps are **not** here. `dumpRef` (e.g. `coredumpctl:abcd1234`)
  points at systemd-coredump's own store.
- Severity: `S0` system core / driver, `S1` Linxira component, `S2` other.
  `triage.reason` records why the state changed (`auto-core` / `auto-driver` /
  `auto-linxira` / `auto-user` / `user-pin` / `mute` / `dedupe`). Read it before
  re-deciding anything — the state may already be deliberate.
- One batch is one program. If a program crashed several times, the batch holds
  several `events/*.json`; reconcile them together.

## Route

1. **Read the batch** — every `events/*.json` for `exe`, `signal`, `pkg`,
   `pkgRepo`, `driverRelated`/`driverHint`, `repeat`, `severity`, `triage`;
   then `backtrace.txt`.
2. **Establish facts, do not guess** — if a shell tool is available, read the
   dump's text form with read-only `coredumpctl` (for example
   `coredumpctl info <dumpRef>`); if you are in the read-only lane (no shell),
   work from `backtrace.txt` alone and say so. Never copy the raw dump into the
   workspace or into git.
3. **Locate the frame** — map the crashing frame to its package and file.
   - A **driver** frame (`libGL*` / `libEGL*` / `libvulkan*` / `nvidia*` /
     `amdgpu*` / `i915*` / `libdrm*`) is actionable even inside a user program —
     call it out.
   - If `pkgRepo == linxira`, the fix belongs to a Linxira repo — name which one.
4. **Decide** — is it (a) a known / upstream-tracked bug, (b) a Linxira-side
   bug, (c) a local / environment issue, or (d) a duplicate of an already-pinned
   `exe`? Prefer "not worth escalating" over a speculative report.
5. **Write `notes.md`** in the batch dir: facts (exe / signal / pkg / frame),
   the likely cause with the evidence that supports it, and a recommendation
   (pin / ignore / report / needs-repro). Keep it short.

## Discipline

- **Read-only by default.** Do not modify the system, install packages, or edit
  anything outside the workspace.
- **No uploads.** Analysis is local; never file an upstream report or send crash
  content anywhere without the user's explicit approval — and check for a
  duplicate first.
- **No shell gymnastics.** Use the file-read / grep / glob tools and the fixed
  read-only `coredumpctl` commands; never build arbitrary shell.
- **Insufficient evidence is a valid answer.** If the backtrace is missing, the
  binary is stripped, or symbols are unavailable, state exactly what is missing
  instead of inventing a cause.