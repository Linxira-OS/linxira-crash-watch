# Linxira Crash Watch

Linxira Crash Watch watches `systemd-coredump`, records text-only crash events,
shows an actionable notification, and — only when the user asks — hands a crash
to the Zeta agent (`zetacode`) inside a local debug workspace.

Capture, notification, and timeout triage all cost **zero tokens**. The agent is
never launched automatically.

## How it works

```
crash → [user service linxira-crash-watch]
          → writes batches/<date>-<slug>/events/<id>.json
          → notification [立即排查 / Pin / 静音]
          → after the timeout (default 6h), auto-triage by severity (0 token)
                       ↓ user action
             exec zetacode --cwd <debug workspace> "<prompt> @<event file>"
```

The watcher and the agent share only the debug workspace directory — no socket,
no HTTP, offline-safe.

## Severity and triage

- **S0** — core component (systemd, dbus, X, desktop shell/compositor, mesa,
  pipewire, NetworkManager, display manager, polkit, pacman, btrfs-progs) or a
  driver-related crash → pinned.
- **S1** — a Linxira-authored component → pinned.
- **S2** — ordinary third-party/user software → ignored by default, but escalated
  to pinned when driver-related, high-frequency, on a critical path, or the
  program was pinned before.

Auto-triage only changes state; it never wakes the agent. Every decision records
a `triage.reason` and is reversible with `restore`.

## Safety boundary

- Unprivileged user service: no root, no network, no arbitrary shell.
- Raw core dumps stay in systemd-coredump's store; only a `dumpRef` is recorded.
- Analysis is local; nothing is uploaded and no upstream report is filed.
- The unattended lane is off by default and, when enabled, uses a read-only tool
  set (`read,grep,glob,lsp`).

## Usage

```bash
linxira-crash status                       # workspace, config, event counts
linxira-crash list --state pending
linxira-crash pin <id>                     # backlog only, 0 token
linxira-crash ignore <id>
linxira-crash restore <id>
linxira-crash mute <program> | --list | --off <program>
linxira-crash investigate <id>             # launches zetacode (spends tokens)
linxira-crash daemon --interval 60         # what the user service runs
```

## Configuration

`~/.config/linxira/crash-watch.toml`:

```toml
[workspace]
path = "~/Linxira/debug"

[triage]
timeout          = "6h"
repeat_threshold = 3

[escalate]
driver_related = true

[lane.unattended]
enabled  = false
schedule = "04:00"
tools    = "read,grep,glob,lsp"
```

See [`document/crash-watch-design.md`](document/crash-watch-design.md) for the
full design.

## Development

Python 3.11 or newer is required.

```bash
python -m pip install -e ".[test]"
pytest
python -m compileall -q src
python -m build
```

---

## 简体中文

Linxira Crash Watch 监视 `systemd-coredump`,把崩溃记录为纯文本事件、弹出带按钮的通知,
并且**只在用户主动触发时**才把崩溃交给 Zeta agent(`zetacode`)在本地 debug 工作区里排查。

捕获、通知、超时自动分流全程 **0 token**;agent 绝不会被自动启动。

## 工作原理

```
崩溃 → [用户服务 linxira-crash-watch]
        → 写 batches/<日期>-<slug>/events/<id>.json
        → 通知 [立即排查 / Pin / 静音]
        → 超时(默认 6h)后按级别自动分流(0 token)
                     ↓ 用户操作
        exec zetacode --cwd <debug 工作区> "<提示词> @<事件文件>"
```

监视端与 agent 只通过 debug 工作区目录解耦 —— 无 socket、无 HTTP、离线安全。

## 分级与分流

- **S0** —— 核心组件(systemd、dbus、X、桌面 shell/合成器、mesa、pipewire、
  NetworkManager、显示管理器、polkit、pacman、btrfs-progs)或驱动相关崩溃 → Pin。
- **S1** —— Linxira 自研组件 → Pin。
- **S2** —— 普通第三方/用户软件 → 默认忽略;但驱动相关、高频、关键路径、或曾被 Pin
  时升级为 Pin。

自动分流只改状态,绝不唤醒 agent;每条决策写入 `triage.reason`,可用 `restore` 撤销。

## 安全边界

- 无特权用户服务:无 root、无网络、无任意 shell。
- 原始 core dump 留在 systemd-coredump 的 store 里,只记录 `dumpRef`。
- 分析全程本地;不上传、不自动上报上游。
- 无人值守通道默认关闭;开启后也只使用只读工具集(`read,grep,glob,lsp`)。

## 用法

```bash
linxira-crash status                       # 工作区、配置、事件计数
linxira-crash list --state pending
linxira-crash pin <id>                     # 只进 backlog,0 token
linxira-crash ignore <id>
linxira-crash restore <id>
linxira-crash mute <program> | --list | --off <program>
linxira-crash investigate <id>             # 启动 zetacode(花 token)
linxira-crash daemon --interval 60         # 用户服务实际运行的命令
```

## 配置

`~/.config/linxira/crash-watch.toml`,字段同上。完整设计见
[`document/crash-watch-design.md`](document/crash-watch-design.md)。

## 开发

需要 Python 3.11 或更新版本。

```bash
python -m pip install -e ".[test]"
pytest
python -m compileall -q src
python -m build
```