# 崩溃诊断与 Agent 唤醒 · 设计稿 (crash-watch)

> 状态:**定稿 v1(2026-10-10)**;实现归属:本仓 `linxira-crash-watch`。
> 目标:系统检测到进程崩溃后,**在用户许可下**把崩溃交给 zeta(我们的 agent)自动排查。
> 相关:发布/测试规范 `linxira-os/docs/RELEASE_STANDARD.md`;路线图 `linxira-os/docs/ROADMAP.md`。

## 1. 背景与目标

- **参考对象(已查证)**:Omarchy 监视 `systemd-coredump`;进程崩溃弹「Process crashed」通知,
  **点击即把崩溃交给默认 agent**,并附内置 `diagnose-crash` skill;可 `omarchy crash mute <program>`、
  `omarchy toggle crash-capture`;上报上游需用户同意。详见文末附录。
- **我们的差异点(刻意为之)**:
  1. **点击才花 token** —— 不照抄"点击即唤醒并自动动手"的放任模式。
  2. **长时间不处理时按级别自动分流** —— 通知没人管也不丢,按严重性自动 Pin / 忽略。
  3. **Pin 累积 + 批处理** —— 长期积累后一口气排查。
- **现状缺口**:Linxira ISO 当前**没有任何 `systemd-coredump` 接线**,信号源尚不存在,必须先补。

## 2. 设计原则

1. **不点不花钱**:捕获 / 通知 / 自动分流全程 **0 token**;只有用户显式触发才唤醒 agent。
2. **唤醒是系统软件的事**:由用户服务 + 通知按钮回调 exec `zetacode`,不是 zeta 自己轮询。
3. **证据本地不外流**:core dump 可能含敏感内存;分析全程本地,**不上传、不自动上报上游**。
4. **可审计、可恢复**:每条自动决策写入 `reason`;忽略/静音均可撤销。

## 3. 命令与前置

- **系统注册命令是 `zetacode`**:由 `packages/packages/linxira-zeta-c-bin/PKGBUILD` 的
  `provides=('zetacode')` 与 `install ... /usr/bin/zetacode` 确认。
  仓库开发态 bin 名为 `zeta`(`packages/coding-agent/package.json`),**脚本里一律用 `zetacode`**。
- **前置条件**:
  1. `systemd-coredump` 纳入 ISO 包清单并启用(信号源);
  2. 目标用户加入 `systemd-journal` 组,以读 coredump(而非给 root)。

## 4. 架构

```
崩溃发生
  │
  ▼
[用户服务 linxira-crash-watch]  ── 写 events/<id>.json(text-only)+ 通知[排查/Pin/静音]
  │                                              │
  │  契约 = debug 工作区目录(无 socket / 无 HTTP)  │
  │                                              ▼
  └────────────────────────────  用户触发 ──►  exec zetacode --cwd <ws> "<提示词>@证据"
```

两端**只通过 debug 工作区目录解耦**,可各自独立演进、离线安全。

## 5. 包与运行身份

**新包 `linxira-crash-watch`(用户态软件)**:

- CLI:`linxira-crash list | pin | ignore | restore | mute | investigate`
- **systemd 用户服务** `linxira-crash-watch.service`(`systemctl --user`,**不是 root 系统服务**)
- 通知(桌面通知 + 按钮动作)+ debug 工作区管理器
- 权限模型:**无特权、无 root、无网络、无任意 shell**

> 选择用户服务的原因:通知属于用户会话、debug 工作区在 `~`、`zetacode` 也以用户身份运行 ——
> 全部落在同一权限域,不需要提权。

## 6. 数据模型(崩溃事件)

```jsonc
{
  "schema": "org.linxira.crash-event.v1",
  "id": "e-2026-10-10-0001",
  "time": "2026-10-10T12:31:02Z",
  "exe": "/usr/bin/kwin_wayland",
  "pid": 1234,
  "signal": "SIGSEGV",
  "scope": "system|user",
  "pkg": "kwin",
  "pkgRepo": "core|extra|linxira|foreign",
  "pkgGroup": ["plasma"],
  "driverRelated": true,
  "driverHint": "libnvidia-glcore",
  "repeat": 3,                       // 同 exe 在窗口内累计次数
  "severity": "S0|S1|S2",
  "triage": {
    "state": "pending|pinned|ignored|investigated",
    "reason": "auto-core|auto-driver|auto-linxira|auto-user|user-pin|mute|dedupe",
    "at": "2026-10-10T18:31:02Z"
  },
  "dumpRef": "coredumpctl:abcd1234"  // 原始 dump 不入库,只存引用
}
```

`reason` 取值:`auto-core` / `auto-driver` / `auto-linxira` / `auto-user`(含高频、关键路径、
学习升级)/ `user-pin`(用户点 Pin)/ `mute`(静音)/ `dedupe`(时间窗内同 exe 已 Pin)。

## 7. 严重性分级(判定顺序:从上到下,命中即定级)

| 级别 | 名称 | 判定条件 | 默认处理 |
|---|---|---|---|
| **S0** | 系统核心 / 驱动 | ① exe / 所属包属**核心组件**(systemd、dbus、xorg-server、plasma-workspace/kwin、gnome-shell/mutter、cosmic-comp/cosmic-session、mesa、pipewire、NetworkManager、sddm/gdm、polkit、pacman、btrfs-progs 等);**或** ② `driverRelated`(backtrace 命中驱动库 `libGL*/libEGL*/libvulkan*/nvidia*/amdgpu*/i915*/libdrm*`,或崩溃包本身是显卡驱动) | **一定 Pin** |
| **S1** | Linxira 自研组件 | `pkgRepo == linxira`(catalog / components / update / config-hub / …) | **一定 Pin** |
| **S2** | 普通第三方 / 用户软件 | 以上均不命中 | 默认**自动忽略** |

**升级规则 —— 把 S2 抬到 Pin(任一命中即升级)**:
1. **驱动相关**:`driverRelated == true`(用户软件引起的驱动错误也 Pin)
2. **高频**:同 exe 累计 `repeat >= repeat_threshold`(默认 3)
3. **关键路径**:崩溃发生在登录会话、包管理器、文件系统/磁盘工具链上
4. **学习**:该程序曾被用户手动 Pin 过

**降级规则 —— 把 S0/S1 降到忽略**:
- 在 **mute 列表**(按程序静音)里
- 时间窗内**已 Pin 过同 exe**(去重,避免重复积攒)

> 分级结果写入 `severity` + `triage.reason`,**可审计、可撤销**。

## 8. 超时自动分流

| 时间点 | 行为 | token |
|---|---|---|
| **T0** 崩溃 | 写事件 + 通知[排查 / Pin / 静音],状态 `pending` | 0 |
| **T0 + 6h**(默认,可配) | 用户既未点按钮也未关通知 → **按级别自动分流** | **0** |
| **T0 + 7d**(可选) | 不再逐条弹,改为每日摘要一条,避免疲劳轰炸 | 0 |

**T0+6h 分流规则**:

| 级别 | 结果 | 可恢复 |
|---|---|---|
| S0 系统核心 / 驱动 | **自动 Pin** | ✅ |
| S1 Linxira 自研 | **自动 Pin** | ✅ |
| S2 已升级(驱动/高频/关键路径/学习) | **自动 Pin** | ✅ |
| **S2 普通用户软件** | **自动忽略归档** | ✅ `linxira-crash restore <id>` |

- **自动分流永不唤醒 agent**:只改状态、不花 token。
- 忽略/静音是**归档不是删除**:事件文件保留,`restore` / 取消静音即可拉回。
- 每条写入 `triage.reason`,便于审计。

## 9. 三条通道(均基于 `zetacode`)

| 通道 | 默认 | 命令 |
|---|---|---|
| **① 交互式** | 可用 | `zetacode --cwd <ws> --session-dir <ws>/.zeta/sessions "排查…证据 @batches/…"` |
| **② 批次** | 可用 | `zetacode --cwd <ws> --goal "处理 backlog.json 中全部 Pin 项"` |
| **③ 无人值守** | **关** | `zetacode --cwd <ws> -p --tools=read,grep,glob,lsp "分析 pending 项,只出结论不改系统"` |

- ③ 的安全设计:**只读工具集**(`--tools=read,grep,glob,lsp`,禁 `bash/write/edit`)+ `-p` 非交互;
  **只产出 `notes.md`,不改系统、不上报、不上传**。要真正修复,回到人工通道。
- 交互式唤醒需终端:用 `konsole` / `cosmic-terminal`,回退 `xterm`(沿用 Linxira 既有回退链)。
- 提示词用 `@file` 前缀内联证据(CLI 位置参数支持 `@文件`)。

## 10. 安全边界(硬约束)

- 服务无特权、无 root;不执行任意 shell;不联网。
- 事件 / 决策文件只写自己的 state 目录。
- core dump 分析全程本地;不自动上报上游、不上传任何内容。
- 自动分流只改状态,绝不触发 agent。
- 无人值守通道默认关闭;开启后也只读。

## 11. 存储与目录

```
~/Linxira/debug/                  # ← debug 工作区(git 仓,只存文本)
├── .gitignore                    # 排除 *.core / *.zst / 大文件
├── INDEX.md                      # 待处理 / 已排查 总览(生成物)
├── backlog.json                  # Pin 待办(含 severity / reason)
├── mute.json                     # 按程序静音列表
└── batches/<日期>-<slug>/        # 一批次 = 一目录(slug = 程序名)
    ├── events/*.json             # 崩溃事件(含 triage)
    ├── backtrace.txt             # 文本证据
    ├── notes.md                  # agent 结论
    └── patch/
```

- **只把文本进 git**(事件 json / backtrace / notes / patch);单批次数十 KB。
- **原始 core dump 不进 git**:留在 systemd-coredump 自己的 store,以 `dumpRef` 引用,
  需要时文本化(backtrace)才入库。
- 磁盘控制:coredump 走 systemd 自带保留策略(`MaxUse`/`KeepFree`/`MaxAge`)+ 我们设上限;
  工作区位置可配置(系统盘紧张则放数据盘);老批次可归档或 squash 后 `git gc`。
- 运行态去重账本(`seen.json`)写在 `$XDG_STATE_HOME/linxira-crash-watch/`,不在工作区内。

## 12. 配置

`~/.config/linxira/crash-watch.toml`:

```toml
[workspace]
path = "~/Linxira/debug"        # 可配置;默认 home

[triage]
timeout          = "6h"         # 通知无响应多久自动分流
repeat_threshold = 3

[escalate]
driver_related = true           # 驱动相关一律升级到 Pin

[lane.unattended]
enabled  = false                # 默认关,手动开
schedule = "04:00"
tools    = "read,grep,glob,lsp" # 开启后也只读
```

## 13. 落点清单

| 仓 | 改动 |
|---|---|
| **`linxira-crash-watch`**(本仓) | CLI + systemd 用户服务 + 通知 + 分级/分流 + 工作区管理器 |
| `linxira-os` | `governance/repositories.yaml` 登记归属;本设计稿迁入本仓 `document/` |
| `packages` | 新增 `linxira-crash-watch` PKGBUILD |
| `linxira-iso-direct` | 包清单加 `systemd-coredump`;用户加入 `systemd-journal` 组 |
| `linxira-zeta` | debug 工作区内置 `diagnose-crash` skill(零安装);可选 `plugins/official/crash-diagnosis/` |

## 14. 最小可用验收(MVP)

1. 崩溃后 6h 内产生事件文件 + 一条带按钮的通知。
2. 点「Pin」只进 backlog、不启动 agent(0 token)。
3. 点「立即排查」在 debug 工作区打开 `zetacode` 会话,并能读到该批次证据。
4. 6h 无人处理:S0/S1 自动 Pin,纯 S2 自动忽略;`restore` 能拉回。
5. 全程事件/决策可审计,无自动上报、无上传。

## 附录:Omarchy 参考(已查证,2026-10-10)

- 官方手册《AI → Crash diagnosis》:Omarchy 监视 `systemd-coredump`;崩溃 → 「Process crashed」通知
  → **点击**把崩溃交给**默认 agent** + 内置 `diagnose-crash` skill(引导 agent 从 core dump 建立事实、
  判断是否值得上报上游)。手动:`omarchy agent crash <pid>`。
- 开关:`Trigger > Toggle > Crash Capture` / `omarchy toggle crash-capture`;
  静音:`omarchy crash mute <program>`(`off` 恢复,单独执行列出)。
- 上报上游**需用户同意**,且先查重。
- 与本设计的差异:Omarchy 为"点击即唤醒并自动动手";本设计为"点击才唤醒(交互式)",
  且增加"超时按级别自动分流 + Pin 批处理"两项,以节省 token。