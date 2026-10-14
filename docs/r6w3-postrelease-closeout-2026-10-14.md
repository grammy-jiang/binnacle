# R6 W3 发布后收尾总清单 — 2026-10-14

> 唯一追踪表；本会话专属。基线：受保护 master 35826539272455d7dc330b37a573c63759efb808（PR #49 已合并，CI 7/7）。历史来源：2026-10-12 Pi 私有 W2-POLISH.md、FDW-PREP / NEXT-STEPS、MACOS-IMPLEMENTATION-TASKS 24-lane 及当前源码/测试。每次任务结束必须重读本表及 origin/master，更新状态/证据，再执行下一个 OPEN；失败必须保留最小可复现案例。

## 严格所有权与门禁

- 只在 Mac 独立克隆 `~/Projects/binnacle-chatgpt-r6w3-followups-20261014`、本会话的 Pi 隔离 QA 树操作；不写 Mac/Pi/sextant 生产 checkout、另一会话的 worktrees、J7 或运行中服务。
- 本会话不修改 Issue #30 的 log maintenance、controller、guardian、watchdog、A3 recovery RPC、启动模块清单或 macOS skip policy 等范围。源变更如有交集，立即标注 `CONFLICT` 并改为独立评审。
- 每个代码项：确凿 RED → 最小 GREEN、受影响的 Mac/Pi 测试、Ruff/双 OS MyPy/Bandit/完整 hooks、独立只读源审查、签名独立提交、GitHub 精确 SHA CI 7/7。不可从旧 SHA 借用门禁。
- 每次迭代按以下顺序：`git ls-remote origin master` → 重读本表 OPEN/BLOCKED → 验证唯一写入路径 → 测试和复审 → 更新本表与证据 → 转下一个 OPEN。不因一个 PR 合并自动宣称生产升级。
- 状态定义：`CLOSED` 已验证；`OPEN` 当前可执行；`REVIEW` 待独立验收；`EXTERNAL` 需要当前客户端/UI/权限/维护窗口；`BOUNDARY` 属于另一会话；`DOCS_ONLY` 由原 SD 明确接受的非实现事项。

## 核心里程碑（核销）

| ID | 状态 | 对账证据 |
|---|---|---|
| R6-CORE | CLOSED | 原 24-lane 的 Mac 原生 Files/Search/Jobs/IPC、独立审核和 CI 已集成；PR #24–#28。 |
| R6-D0 | CLOSED | Mac 047dc2f 受控发布回执 DEPLOYED、33/33 gate、0 中断，Doctor 24/24、Chat 实际调用。 |
| SEC-FU-14 | CLOSED | Linux FD-relative 写入安全 PR #31 + fsync/parent 顺序 PR #33；复审与 CI 成功。 |
| PX1B-F4-GLOB | CLOSED | PR #49，签名 c38687e / merge 3582653，Mac 151 / Pi 85 affected，实际 Linux 非 UTF-8 文件名复现及合并后七项 CI 通过。 |
| W2-01/10/11 | CLOSED | src/binnacle/features/files/tools/read_file.py 先拒绝特殊文件、非 Linux 有界读、从真实 FD 报 bytes；test_r6w3_rf1_read_file.py。 |
| W2-02 | CLOSED | search_text_verify.verify_adaptive 减掉不安全候选 count 并重新计算 candidate_files，test_r6w3_sr1_search_polish。 |
| W2-03 | CLOSED | fd_walk.open_verified 必须传 parent_fd；不存在路径重开模式，OS1/X3a2 tests。 |
| W2-04 | CLOSED | files/list_files_glob 与 search_text 统一 too_many_open_files 拒绝；test_r6w3_sp1_glob_shortage。 |
| W2-05/07/08/09 | CLOSED | manager 模块已拆分；list_files 文档与 special-file 裁决完成；fd_chain/rg_env 移入 features.files，无双向包依赖。 |
| W2-06/12 | CLOSED | list_files._opened 映射 ELOOP/EMFILE 等且有 nearby hint；glob 非 regular 项省略；对应 SP1 tests。 |
| RL1-F1/F2/F5 | CLOSED | Darwin exit queue ping 观测、bounded lock backoff、reaper 错误态测试已入库。 |
| RL1-F3/F4 | DOCS_ONLY | 原 SD-83：崩溃退出记录窗口标 UNKNOWN，维持已接受的设计，不补虚假的 sidecar guarantee。 |
| PX1B-F2 | CLOSED | 特殊文件测试 AF_UNIX 位于专属 ~/.local/state/bt/px1c，不占用 /tmp MCP 根；PX1-a4 测试。 |

## 逐项清空的工程待办（完成一项即更新）

| ID | 状态 | 独占源代码/执行位置 | 验收条件及证据 |
|---|---|---|---|
| PX1B-F4-SEARCH | REVIEW | features/search reducer、materialized collector、输出包装；Mac 独立克隆 + Pi QA | 非 UTF-8 `rg --json` 文件名被静默省略时给出安全的计数提示；materialized/streaming、names-only、截断、permission、adaptive、glob；无路径/转义泄露。 |
| PX1B-F3 | OPEN | Linux legacy edit_file/write_file 精确拒绝代码 | Linux/Darwin 公共拒绝有一致 `telemetry_code`、无文字破坏；限定被触及的错误。 |
| FDW-6 | OPEN | Darwin file_traversal 的 held-parent errno/classification | ELOOP 与 ENOTDIR 按 held parent FD 的 no-follow fstat 区分，不用额外 pathname 探测，负例拒绝不降级。 |
| FDW-8 | OPEN | Files/Search listing 的 lstat/fstatat 错误策略 | 对 ENOENT、EMFILE、EACCES/EPERM、其他 OSError 的选择、丢弃/保留/附注一致；相同 Mac/Linux XOS rows。须保留不安全路径 fail-closed。 |
| FDW-11 | OPEN | 完全隔离的原生 Mac 10,000 文件只读性能基准 | 与 Linux 同结构校验，记录硬件/次数/median/每文件相对比；仅 Darwin > 1.5x 时考虑专项优化。 |
| FDW-13 | OPEN | Darwin 内核 F_GETPATH 的评估/基准，不涉及服务 | 验证同一 FD 上根路径重检的安全收益、别名/搬迁/路径长度与耗时；若性能或安全证据不足，记录明确 NO_GO，不硬加。 |
| FDW-A | OPEN | File walk 一次开链路 API 设计核销 | 核对当前 FDW-B1 one-walk 消费者；仍存重复 resolve→open 则做小范围修复与 XOS 否定测试，否则记录 NO_CHANGE。 |
| PX1B/TEST-STRICT | OPEN | Files/Search 专属 tests/ 文档 | 回归可在 Mac/Linux 完全执行；对当前所有低优先级旧项逐个标记复现/已修/设计豁免，禁止重复开发。 |
| R6-EVIDENCE | OPEN | 独立关闭报告文档（非原 Supervisor 私有 ledger） | 四列区分实现、测试、合并与实装；重审全部旧清单，无剩余非阻断 OPEN。 |

## 无法通过普通代码提交完成的门禁（不允许假报）

| ID | 状态 | 条件 |
|---|---|---|
| E1-WORK | EXTERNAL | Work 实际 UI 中对同一 MCP 的真实授权工具调用、回执；无外部客户端驱动时记录 NOT_VERIFIED。 |
| A4-TCC | EXTERNAL | 经用户批准的 macOS 真实 TCC-denied 路径/权限样例；不运行 tccutil、不扩大 TCC grant。 |
| RELEASE-CONVERGE | EXTERNAL | GitHub 3582653 vs 三台生产机 278af9c；只在其它会话完成开发与 Jobs Manager/MCP/RPC 归零、独立部署门禁合格时逐台安全更新。 |
| DEV-TOOLS | OPEN | 各 OS uv/hooks、rg 版本实际 Doctor 状态复核，区分非致命 warning、真实阻断；不动生产环境。 |
| ISSUE30 | BOUNDARY | macOS 日志归档、privileged controller、crash guardian 与生产 prune 由另一聊天会话独占；本表不领取任何源码写权限。 |

## 本轮执行日志

- 2026-10-14：新建本会话隔离收尾分支，已核查主版本为 3582653；先从 PX1B-F4-SEARCH 开始。每项后追加一个带精确 SHA、测试数、CI/审查状态的记录。


- PX1B-F4-SEARCH：旧 SHA 3582653 上先 RED 8/10；实现后 Mac/Pi 各 67 selected PASS，Pi 真实系统 ripgrep 非 UTF-8 名称 streaming/materialized 均 PASS，Mac 完整 pre-commit PASS。独立源码审核待取得后才 CLOSED。
