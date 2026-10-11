# linxira-crash-watch · Agent 开发规范

> **档位**:A · 系统源仓
> **本仓职责**:崩溃捕获、分级/分流、以及**经用户许可**的 agent 唤醒。
> 通用约束见工作区总纲 `f:\Linxira-OS\AGENTS.md` 与发布规范 `linxira-os/docs/RELEASE_STANDARD.md`;
> 本文只写本仓特有内容。设计依据见 `document/crash-watch-design.md`。

## 职责与边界

- 监视 `systemd-coredump`(经 `coredumpctl`),把崩溃落成**纯文本**事件、弹桌面通知,
  并在通知长时间无人处理时**按级别自动分流**。捕获 / 通知 / 分流全程 **0 token**。
- **只有用户显式触发**才唤醒 agent;唤醒一律 exec **`zetacode`**(系统注册名,由
  `packages/packages/linxira-zeta-c-bin` 的 `provides=('zetacode')` 提供),**绝不写 `zeta`/`omp`**。
- 运行身份是 **systemd 用户服务**(`systemctl --user`),**不是 root 系统服务**;无特权、无网络、无任意 shell。
- 与 agent 的唯一契约是 **debug 工作区目录**(默认 `~/Linxira/debug`,git 仓、只存文本);
  两端无 socket、无 HTTP、离线安全。
- 原始 core dump **不进工作区、不入 git**,只留 `dumpRef`;分析全程本地,不上传、不自动上报上游。

## 目录布局

- `src/linxira_crash_watch/`:`about.py`(注册名/版本)、`config.py`(TOML 配置与时长解析)、
  `events.py`(事件模型 + 事件库)、`triage.py`(S0/S1/S2 分级与分流,纯函数)、
  `workspace.py`(debug 工作区管理器)、`notify.py`(桌面通知 + 按钮)、
  `watcher.py`(`coredumpctl` 采集 + 超时分流)、`lanes.py`(三条通道的 argv 构造)、`cli.py`。
- `src/linxira_crash_watch/skills/diagnose-crash/SKILL.md` —— 内置诊断技能(随包);
  `workspace.ensure()` 首次创建时物化到 `<ws>/.agents/skills/`(零安装,agent 标准路径发现)。
- `data/`:`linxira-crash-watch.service`(用户服务单元)、`linxira-crash-watch.preset`
  (安装为 `lib/systemd/user-preset/90-linxira-crash-watch.preset`;首启 `systemctl preset-all`
  按 preset 自启用户服务,同 org 既有 `linxira-update` 模式)、`org.linxira.CrashWatch.desktop`、`.metainfo.xml`。
- `document/crash-watch-design.md` —— 定稿设计稿(权威)。
- `tests/` —— pytest;纯函数策略在无 systemd / 无桌面会话下即可测。

## 关键契约(勿破坏)

- 事件 schema 恒为 `org.linxira.crash-event.v1`(`about.SCHEMA` / `events.SCHEMA`),字段名见设计稿 §6。
- 严重性/分流规则集中在 `triage.py`(纯函数);`watcher.py` 只调用,不得内联另一套判定。
- 唤醒命令只经 `lanes.py` 构造;**无人值守通道默认关**(`[lane.unattended].enabled = false`),
  开启后也只读(`--tools=read,grep,glob,lsp`)。
- 外部命令一律**固定 argv 允许列表**(`coredumpctl`、`pacman -Qoq`/`-Qi`、`notify-send`、`git init`、
  终端 `konsole`/`cosmic-terminal`/`xterm`),**无 shell**;位置参数经 `_check_arg` 拒绝 `-` 开头的注入。
- 运行态去重账本(`seen.json`)写 `$XDG_STATE_HOME/linxira-crash-watch/`,**不写进工作区**。
- 内置技能的物化位置固定为 `<ws>/.agents/skills/diagnose-crash/SKILL.md`(标准 agent 路径);
  只在首次创建时写入,不覆盖既有内容。

## 本地校验

CI(矩阵 python 3.11/3.12/3.13)执行:

```sh
python -m pip install ".[test]"
pytest
python -m compileall -q src
python -m build
python -c "import xml.etree.ElementTree as E; E.parse('data/org.linxira.CrashWatch.metainfo.xml')"
```

CLI 自检:

```sh
linxira-crash status
linxira-crash list --state pending
linxira-crash investigate <id> --dry-run
linxira-crash daemon --once
```

## 版本与发布

- 版本唯一来源是本仓根 `VERSION`(当前 `0.1.0`);`pyproject.toml` 的 `version` 必须同步。
- 改 `VERSION` 触发 `.github/workflows/release.yml`(分支 `main`)自动建 Release,进入 `[linxira]` 全自动链。**禁止手工 bump**。

## 禁区

- 不得让捕获 / 通知 / 自动分流唤醒 agent —— 只有用户显式操作才花 token。
- 不得新增 shell 执行、任意路径/任意 argv 输入;不得删除 core dump;不得让无人值守通道写系统或联网。
- 不得把原始 core dump / 大二进制写入 debug 工作区(工作区只存文本)。
- 不引入 `cachyos` / `aur` / `seafoam`;不直接 `sudo`/`su`/`doas`/`run0`。
- 不 `git add -A`(勿带入 `dist/`、`.pytest_cache/` 等产物)。

## 关联文档

- `README.md`、`document/crash-watch-design.md`。
- 工作区总纲;发布规范;`packages/docs/AGENT-GUIDELINES.md`。