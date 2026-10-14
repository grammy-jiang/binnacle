# R6 W3 发布后收尾 — 独立验收证据

记录时间：2026-10-14（AEDT）。范围：本会话 Files/Search/FDW 发布后工作包。单一清单见 r6w3-postrelease-closeout-2026-10-14.md。原则：将源码、测试、受保护主分支合并、生产运行分别记录，不以一项代替另一项。

## 源码与部署四层状态

| 工作包 | 实现 | 测试 / 独立审查 | 合并 | 生产 |
| --- | --- | --- | --- | --- |
| R6 W3 核心 Mac 原生 | 已完成 | 原 R6 W3 QA/CR3 通过 | 已合并 | Mac 受控部署回执为 DEPLOYED；服务正常 |
| SEC-FU-14 Linux FD 写入安全 | 已完成 | Linux 回归/安全复审通过 | PR #31、#33 已合并 | 最新功能的再次同步未完成 |
| PX1B-F4-GLOB | 已完成 | Mac/Pi 回归及 CI 全绿 | PR #49 合并至 3582653 | 三机当前版本旧于该提交 |
| PX1B-F3 edit/write 错误遥测 | 已完成 | Mac/Pi 各 61 项、两组 CI 7/7 | PR #53 合并至 68999c5 | 尚未同步三机 |
| PX1B-F4-SEARCH | 已完成 | Mac/Pi 各 125 项、独立 P1/P2 复审、两组精确 CI 7/7 | PR #51 合并至 61a0657 | 未部署 |
| FDW-8 list/glob lstat 错误分类 | 已完成 | Mac/Pi 各 109 项、独立 P1/P2 复审、两组精确 CI 7/7 | PR #56 合并至 469e31f | 未部署 |
| FDW-6 Darwin held-parent errno | 已修复，仅区分拒绝的 ELOOP/ENOTDIR | Mac/Pi 各 521 项通过、2 项预期跳过；Mac Python 3.14 定向 160 项通过；两组精确 CI 17/17 | PR #60 合并至 cefc072b，Issue #57 已关闭 | 尚未部署 |
| FDW-11 10k 文件性能调查 | 已完成调查，未做风险优化 | 同机私有基准和 cProfile | 非代码调查 | 无需部署 |
| FDW-13 F_GETPATH 可行性 | NO_GO（安全语义不足） | rename、alias、unlink 原生负例及每次调用成本 | 非代码调查 | 禁止启用 |
| FDW-A 一次 FD 链路审查 | NO_CHANGE | 私有 Darwin grant 的 open_read/write_bytes FD 次数核验通过 | 现有设计无需更改 | 保留现有路径 |
| Work UI E2E / TCC 真实拒绝 | 尚无有效外部证据 | NOT_VERIFIED | 不适用 | 未声明通过 |

## FDW-8 故障边界

旧行为：LIST 模式无条件丢弃每个 os.lstat OSError；GLOB 模式在未知错误时保留仅有路径、没有元数据的成功形状条目。新规则仅允许已知路径竞态/权限拒绝省略（ENOENT、ENOTDIR、ELOOP、EACCES、EPERM）；EMFILE/ENFILE 明确拒绝为 too_many_open_files，其他 I/O 如 EIO/EINVAL 明确拒绝为 file_io_failed。适配既有不携带 errno 的 PermissionError/NotADirectoryError/FileNotFoundError。保留 fd-relative、O_NOFOLLOW、完整 FD 清理策略。

证据：冻结 a5d87df 上新测试 RED 6 failed/12 passed；修复后 Mac/Pi 各 109 定向测试通过；“先正常一条，后 EIO 一条”没有成功部分返回且无 FD 泄漏；Mac 全仓 Ruff、MyPy 两 OS、Bandit、架构检查均通过；独立 reviewer PASS P1/P2。既有 Linux link_target_info 在 symlink 的目标读取阶段除 FD 耗尽外会省略其他错误，属于此前另一个经过批准的 SD-74 边界，不应误宣称所有链接目标路径都已调整。

## FDW-11 独立性能调查

测试文件全部置于 Mac 私有临时根：100 个子目录，共 10,000 个长度小的常规文件。四轮、首轮作热身。DarwinFileAccess.list_entries（含每目录完整遍历、默认 ignore 和类型确认）暖态中位数 0.22632 s；系统 rg --files + Python glob 条目元数据处理 0.06040 s，比值 3.747。两路径并非严格同等语义：不能据此判断安全校验冗余。cProfile 单轮 profile 模式：约 0.489 s 总时间，glob_matches 20,000 次累积约 0.292 s，checked_open 10,100 次，posix.open 10,101 次。性能候选是重复的 glob 解析、cache 装饰和路径分段对象创建；必须先进行严格等价、权限/链接/竞态负例和本机 P95 对比。禁止以性能理由移除 no-follow 或 FD identity 校验。

## FDW-13 NO-GO 决策

同一 Mac 临时目录打开的持有 FD，F_GETPATH 在重命名后能返回新的 canonical 路径，symlink alias 也以 canonical 形式报告。但目标目录 unlink 后仍会返回已经不存在的旧字符串。四轮 10,000 次调用的每次中位数：F_GETPATH 587ns、fstat 466ns（1.26x）。路径字符串检测与使用之间仍有竞态，不能取代打开的 grant/相对目录 FD 作为授权边界。不向生产增加 F_GETPATH 检查。若未来只作为可选诊断，再单独审查空路径、名称超长和权限场景。

## FDW-A NO_CHANGE

在独立私有 Mac 目录，以 DarwinFileAccess grant 执行 open_read(sub/target.txt) 和 write_bytes(sub/new.txt)：读取阶段实际发生一次父目录 sub 相对打开和一次目标文件相对打开，写入阶段父目录 sub 相对打开一次，返回 3 字节写入回执。现有 FDW-B1 测试约束描述符链路和竞态拒绝；普通读写路径没有冗余的“resolve 后重新路径打开”行为。因此不实施额外的重构。链接解析还有独立文本策略和无跟随链路，不应将此断言外推至所有复杂 link 场景。

## 受控运行环境与阻断

- Mac（2026-10-14）：uv 0.12.22；rg 15.2.0；本机 Doctor 24/24 OK。R6 W3 受控部署回执此前 33/33 通过，无中断用户 Job。
- Pi、sextant：uv 0.12.24；rg 14.1.1（非致命 warning）。Pi Doctor 31 OK/2 WARN；sextant 32 OK/1 WARN，exit 0。安装 rg 新版本会改变其他活动作业的工具环境，本会话不在运行中操作。
- PR #51 先前 SHA 9136fcc 的一组 CI 7/7 成功，另一组在 Python 3.11 的 Issue #30 test_log_e2e_transaction.py raw_unlink 下，两次出现 flock EAGAIN（1 failed/6879 passed）。不能绕过精确 CI 或修改另一个会话的生产日志维护代码。
- FDW-8 的 Mac fast pre-push 在未修改的 a5d87df 基线也出现 test_r6w3_e1d_manager_scope 两项导入模块预期差异：新维护 fence 模块不在旧的严格预期中。这不是本次 Files 源码引起，不能通过禁用质量门禁掩盖。
- GitHub 最新保护分支的源码与三台运行机器的 278af9c 不一致。生产同步只能在独立审查、确认其他开发任务/Job Manager 零活动以及可回滚维护窗口下逐台进行。Mac 与两台 Pi 的生产目录从未在本次调查中直接改动。
- Work UI 的独立 E1 验收和真实 macOS TCC 拒绝需要外部客户端及权限样本，本轮未获取证据，不得标记 PASS。Issue #30 主实现仍由另一会话负责。

## 2026-10-14 集成收尾对账

GitHub 在此时受保护 master 为 61a0657，其第一父提交 469e31f 集成 FDW-8，另一父提交 3ed2545 含 PX1B-F4-SEARCH 与独立本报告。PR #51/#56 各自在最终签名头提交上两组七项必需 CI 均通过。两个会话的文件所有权无冲突（PR #51 合并前以 Git 差异对比验证）；Mac/Pi/sextant 的运行代码没有自动同步。PR #51 的旧头 9136fcc 上曾重现的日志事务 flock 测试失败仍记为历史风险，不能据新代码集成推断真正的日志生产维护已获授权。

截至原 21:23 快照，FDW-6 尚受工作站安全检查阻止；其后已在新的独立克隆完成安全修复、CI、合并及 Issue #57 核销，见以下 23:36 补充。仍需外部完成 Work UI 真实端到端、TCC 实测拒绝及维护窗口内的三设备安全同步。绝不因代码合并就声称已执行生产升级。

## 2026-10-14 23:36 AEDT — FDW-6 及清单最终源码验收

在 GitHub 受保护 master cefc072b，FDW-6 的 PR #60 已合并、Issue #57 已关闭。隔离分支先复现 RED 2/3，之后签名 6475a9b 修复使用持有父目录 FD 的无跟随 metadata 诊断，并保留原拒绝策略。Mac 与 Pi 各 521 passed / 2 expected skipped，Mac Python 3.14.8 额外 160 passed；双平台 MyPy 与 pre-commit、架构、模块大小、安全检查通过，两组精确头 GitHub CI 最终 17/17 成功。

PR #60 第一轮 Python 3.14 中另一会话的 Issue #30 flock EAGAIN 测试失败，但在不跳过测试、不修改日志维护源码的情况下，同 SHA 正式重跑成功。原 master 65ece951 曾有独立 Issue #30 recovery RPC socket 拒绝的 CI 波动。这些测试风险交还 Issue #30 owner，不能把 FDW-6 合并当作日志维护稳定性或生产授权证据。

本会话 Files/Search 代码收尾完成；外部 E1-WORK、A4-TCC 和 RELEASE-CONVERGE 仍为 NOT_VERIFIED/EXTERNAL。旧生产服务与实际配置不因 GitHub 更新自动升级，且 Issue #30 C1–C4 独立验收仍未闭环。
