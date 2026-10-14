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
| --- | --- | --- |
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
| --- | --- | --- | --- |
| PX1B-F4-SEARCH | CLOSED | features/search reducer、materialized collector、输出包装；Mac 独立克隆 + Pi QA | 非 UTF-8 `rg --json` 文件名被静默省略时给出安全的计数提示；materialized/streaming、names-only、截断、permission、adaptive、glob；无路径/转义泄露。 |
| PX1B-F3 | CLOSED | Linux legacy edit_file/write_file 精确拒绝代码 | Linux/Darwin 公共拒绝有一致 `telemetry_code`、无文字破坏；限定被触及的错误。 |
| FDW-6 | CLOSED | Darwin file_traversal 的 held-parent errno/classification | ELOOP 与 ENOTDIR 按 held parent FD 的 no-follow fstat 区分，不用额外 pathname 探测，负例拒绝不降级。 |
| FDW-8 | CLOSED | Files/Search listing 的 lstat/fstatat 错误策略 | 对 ENOENT、EMFILE、EACCES/EPERM、其他 OSError 的选择、丢弃/保留/附注一致；相同 Mac/Linux XOS rows。须保留不安全路径 fail-closed。 |
| FDW-11 | CLOSED | 完全隔离的原生 Mac 10,000 文件只读性能基准 | 与 Linux 同结构校验，记录硬件/次数/median/每文件相对比；仅 Darwin > 1.5x 时考虑专项优化。 |
| FDW-13 | CLOSED | Darwin 内核 F_GETPATH 的评估/基准，不涉及服务 | 验证同一 FD 上根路径重检的安全收益、别名/搬迁/路径长度与耗时；若性能或安全证据不足，记录明确 NO_GO，不硬加。 |
| FDW-A | CLOSED | File walk 一次开链路 API 设计核销 | 核对当前 FDW-B1 one-walk 消费者；仍存重复 resolve→open 则做小范围修复与 XOS 否定测试，否则记录 NO_CHANGE。 |
| PX1B/TEST-STRICT | CLOSED | Files/Search 专属 tests/ 文档 | 回归可在 Mac/Linux 完全执行；对当前所有低优先级旧项逐个标记复现/已修/设计豁免，禁止重复开发。 |
| R6-EVIDENCE | CLOSED | 独立关闭报告文档（非原 Supervisor 私有 ledger） | 四列区分实现、测试、合并与实装；重审全部旧清单，无剩余非阻断 OPEN。 |

## 无法通过普通代码提交完成的门禁（不允许假报）

| ID | 状态 | 条件 |
| --- | --- | --- |
| E1-WORK | EXTERNAL | Work 实际 UI 中对同一 MCP 的真实授权工具调用、回执；无外部客户端驱动时记录 NOT_VERIFIED。 |
| A4-TCC | EXTERNAL | 经用户批准的 macOS 真实 TCC-denied 路径/权限样例；不运行 tccutil、不扩大 TCC grant。 |
| RELEASE-CONVERGE | EXTERNAL | GitHub 截至 2026-10-14 23:35 的受保护分支 cefc072b vs 三台设备先前安装版本 278af9c；只在其它会话完成开发与 Jobs Manager/MCP/RPC 归零、独立部署门禁合格时逐台安全更新。 |
| DEV-TOOLS | CLOSED | 各 OS uv/hooks、rg 版本实际 Doctor 状态复核，区分非致命 warning、真实阻断；不动生产环境。 |
| ISSUE30 | BOUNDARY | macOS 日志归档、privileged controller、crash guardian 与生产 prune 由另一聊天会话独占；本表不领取任何源码写权限。 |

## 本轮执行日志

- 2026-10-14：新建本会话隔离收尾分支，已核查主版本为 3582653；先从 PX1B-F4-SEARCH 开始。每项后追加一个带精确 SHA、测试数、CI/审查状态的记录。

- PX1B-F4-SEARCH：旧 SHA 3582653 上先 RED 8/10；实现后 Mac/Pi 各 67 selected PASS，Pi 真实系统 ripgrep 非 UTF-8 名称 streaming/materialized 均 PASS，Mac 完整 pre-commit PASS。独立源码审核待取得后才 CLOSED。

- PX1B-F4-SEARCH 第二次独立复审 PASS：额外 P2（保留 Darwin skipped_changed/skipped_io_error）与 P3（最终拒绝不得记录成功终态）全部修复；新增精确回归。Mac/Pi 各 125 affected PASS；完整 MyPy/Ruff/Bandit/architecture hooks PASS。等待最终签名提交的 GitHub 7/7 CI 再核销 CLOSE。

- DEV-TOOLS 只读检查：Mac rg 15.2.0、uv 0.12.22 在 pyproject 约束内、Doctor 24/24 OK；Pi/sextant uv 0.12.24，rg 14.1.1（均 Doctor WARN）；Pi Doctor 31 OK/2 WARN（rg,journal），sextant 32 OK/1 WARN（rg），两台 exit 0。版本安装/重启不在本会话直接执行。

- BLOCKED_CI means a code-complete item whose exact-SHA required GitHub tests fail; no merge/deploy until corrected and reverified.
- 2026-10-14 19:37 AEDT: PX1B-F3 merged through protected PR #53 as 68999c5; Mac/Pi each 61 affected tests and two exact SHA workflows green. Only production convergence remains external.
- PX1B-F4-SEARCH PR #51 exact SHA 9136fcc: run 38520926773 green; run 38520931697 Python 3.11 fails on both attempts (attempt 2 job 115759148919), Issue #30 log_e2e_transaction.py raw_unlink fixture gets flock EAGAIN. One failed and 6,879 passed. Recorded in PR #51 comment issuecomment-6164393735. Do not bypass CI or modify another session's Issue #30.
- FDW-6: Private Mac RED 2/3 reproduces ELOOP vs ENOTDIR misclassification. Fix in an isolated new branch requires safe host file access implementation and independent tests; do not modify production.
- FDW-11: 10k files / 100 dirs on private Mac, four trials (median last three): DarwinFileAccess 0.22632s, full system ripgrep glob path 0.0604s, ratio 3.747. Above 1.5 investigation threshold but semantic differences remain. cProfile shows 20k glob_matches consume 0.292s of 0.489s measured profiler time; 10,101 open calls. Do not remove security checks as speculative speed optimization.
- FDW-13: Private Mac F_GETPATH on same fd tracks rename, median 587ns vs fstat 466ns (ratio 1.26), symlink alias canonicalized; after unlink an open fd can return old string while path is missing. No continuous-containment guarantee; security GO/NO_GO not yet issued.

- 2026-10-14 21:10 AEDT: FDW-8 在受保护 master a5d87df 的独立开发分支复现 6 个 RED 用例，修复后 Mac/Pi 各 109 个 Files、race、symlink 定向用例通过。独立源码安全复审无 P1/P2，签名 93c58a81、Draft PR #56 正等 CI。所有实现保持 fd-relative/no-follow；合成 PermissionError 若不带 errno 也保留原 omission contract。
- FDW-8 的 Mac 全量 pre-push 还受不相关的 Issue #30 模块导入清单测试失败阻挡；在完全未修改的 a5d87df 独立基线中可重现 2 个 test_r6w3_e1d_manager_scope 失败。不得因该基线问题推断本 PR 的 Files 代码错误，也不能绕过质量门禁。
- FDW-A CLOSED (NO_CHANGE): 在 Mac 真实的 /private/tmp 私有根、打开的 DarwinFileAccess grant 中，open_read 子目录一次 + 正式文件一次；write_bytes 子目录一次且写入正常。既有 FDW-B1 tests 提供负例；不改内核 FD 策略。
- FDW-11 CLOSED (BENCHMARK + RECOMMENDATION): 私有 Mac 10k 文件、100 目录暖态 Darwin 0.22632 秒，rg --files + glob 0.06040 秒，差 3.747 倍；cProfile 的 glob_matches 20k 次是显著成本。两条不同语义路径不能直接按该比值证明安全冗余；先用等价 glob 编译缓存与权限负例做性能专项，不删除 no-follow/identity 校验。
- FDW-13 CLOSED (NO_GO): F_GETPATH 可追踪 rename，但经 symlink 打开返回 canonical 名称、unlink 后仍可能返回已经不存在的旧路径，不能替代根目录 FD/grant identity 控制；测试成本约 587ns vs fstat 466ns。禁止仅凭字符串认为路径仍受授权。
- DEV-TOOLS CLOSED (READONLY): Mac uv 0.12.22, rg 15.2.0, Doctor 24/24 OK；Pi、sextant uv 0.12.24，rg 14.1.1，Doctor 31 OK/2 WARN 与 32 OK/1 WARN，exit 0；不改变生产环境下其他活动进程可能使用的工具。

- 2026-10-14 21:23 AEDT: FDW-8 PR #56 at signed 93c58a81 merged protected as 469e31f. Both 7/7 exact-head CI workflows SUCCESS; Mac/Pi each 109 affected tests and independent P1/P2 review PASS. It is code-integrated but not yet deployed on any node.
- PX1B-F4-SEARCH PR #51 at signed final integration 3ed2545, two exact-head 7/7 GitHub workflows SUCCESS, merged protected as 61a0657. Previous unrelated E2E test lock failure on old head is historical; on the new merged-source head the Python 3.11 runs passed. Code integrated; post-merge master CI independently tracked, not a production claim.
- FDW-6 still unresolved: evidence-only RED 2 failed/1 passed in standalone Mac private clone, issue [Issue #57](https://github.com/grammy-jiang/binnacle/issues/57) created. Source modification was blocked by workstation safety checks and was not attempted again by a different route. Keep BLOCKED_TOOL until a safely reviewed change truly passes tests/CI.
- PX1B/TEST-STRICT CLOSED for this conversation's OWNED Files/Search regressions: both OS affected fixtures plus PR #49/#53/#56/#51 final exact-head protected 7/7; this does not imply that unrelated Issue #30 external/production tests are certified.
- R6-EVIDENCE CLOSED as a source artifact: docs/r6w3-postrelease-evidence-2026-10-14.md is in protected master through PR #51, with code/test/merged/deployed columns and honest external status.

## 2026-10-14 23:36 AEDT — FDW-6 代码收尾核销

- FDW-6 CLOSED：在新隔离 Mac 克隆的最新 master 基线上先重现原有 2 failed / 1 passed，再通过 held-parent os.stat(name, dir_fd=parent, follow_symlinks=False) 仅对已拒绝的 ELOOP/ENOTDIR 做诊断。无二次 pathname open；stat 失败或目录类型模糊时仍返回原错误；外部 UnsafePath 拒绝代码不变。
- 签名提交 6475a9b，PR [#60](https://github.com/grammy-jiang/binnacle/pull/60) 已受保护合并至 cefc072b；Issue [#57](https://github.com/grammy-jiang/binnacle/issues/57) CLOSED。Mac 与独立 Pi 各 521 passed / 2 expected skipped；Mac Python 3.14.8 额外 160 passed；两台 pre-commit、双目标 MyPy、架构与安全检查通过。PR 精确头两组 CI 最终 17/17 成功。
- 历史 CI 波动保留：PR #60 第一轮 Python 3.14 失败于非 FDW-6 的 Issue #30 log_transaction_controller/observer 锁竞争（flock EAGAIN），同一 SHA 重新运行通过。PR #58 合并后 master 曾在另一 Issue #30 recovery RPC socket fixture 出现 ConnectionRefusedError；Issue #30 的生产验收与测试稳定性不因本项合并而假报完成。
- 本收尾范围无未分类的代码 OPEN、REVIEW 或 BLOCKED_TOOL；真正剩余三个 EXTERNAL：E1-WORK、A4-TCC、RELEASE-CONVERGE。Issue #30 仍是另一会话专属 BOUNDARY，自动日志 prune 保持 OFF。Mac/Pi/sextant 已安装服务没有因为 PR #60 合并而部署或重启。
