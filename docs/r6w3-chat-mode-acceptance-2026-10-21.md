# R6 W3 — ChatGPT Chat Mode 真实客户端验收（2026-10-21）

本文件是对 2026-10-14 发布后清单的**有时间戳的补充**。用户于 2026-10-21 明确当前项目仅针对 ChatGPT Chat Mode。Work Mode 不在交付范围内，不作为阻塞、不能混入 Chat 模式证据。该限定不修改过去已冻结的源计划和历史验收记录。

## 产品契约与验收范围

- Binnacle 的完整服务器含八项工具：read_file、list_files、search_text、edit_file、write_file、run_command、job_status、stop_job。
- 当前 Binnacle Settings.client_tools 的 openai-mcp 客户端白名单有意只提供六项：read_file、list_files、search_text、run_command、job_status、stop_job；edit_file/write_file 仍在内部 Files 子服务注册，通过客户端策略不可见。其设计缘由是旧 ChatGPT 客户端以 run_command 脚本处理结构化文件修改，减少工具数量和令牌开销。
- 本轮只能把**六工具 Chat Mode 白名单**作为公开接口验收；不能将未开放的两个工具标记为 Chat Mode PASS，也不通过特殊 HTTP 调用绕过客户端隐藏策略。
- macOS stop_job 明确不可用：macOS 的 run_command 当前只执行前台任务，job_status 仅持有已完成结果；这属于已接受平台差异，不应错误要求它像 Linux 一样停止 durable background job。

## 来自 ChatGPT Chat Mode 的直接 MCP 工具调用

| 工具 | MacBook Pro | Raspberry Pi | Sextant | 证据 |
| --- | --- | --- | --- | --- |
| read_file | PASS | PASS | PASS | 从每个主机的 Binnacle 源码目录读取 AGENTS.md 指定行，均得到文字 |
| list_files | PASS | PASS | PASS | 列举各主机项目目录，均得到合法文件/目录条目 |
| search_text | PASS | PASS | PASS | 在 README.md 中匹配 Binnacle，均得到带行号结果 |
| run_command | PASS | PASS | PASS | 远程运行一次短 Python 命令，分别返回 OS=darwin / linux / linux，exit=0 |
| job_status | PASS | PASS | PASS | 查询前述真实工具调用所生成的 job_id，均确认 exited/exit=0 |
| stop_job | UNAVAILABLE (预期限制) | PASS | PASS | Linux 两机仅停止本轮自建 sleep 测试 Job，SIGTERM=15，复查 exited |

Linux 测试 Job 收据：主 Pi 为 bcf093bf52c1，Sextant 为 47310beca04e，均由本次 run_command 创建，在 stop_job 后复核退出；未停止其他开发或生产 Job。普通命令的 job_id 分别为 Mac 1d538c413ac1、主 Pi 4cbb7400c363、Sextant f5c37ff2caf7。

验收结论：**E1-CHAT 为 CLOSED（已配置且已批准的六工具 Chat Mode 表面）**。它不表示完整八工具均暴露给 ChatGPT，也不表示 Mac 达成 Linux 等价的后台停止能力。

## macOS 权限拒绝与真实 TCC 边界

- Mac 部署快照 ab60a33e 的 tests/platform/darwin/test_files_tcc.py：40 passed；包括注入的 EACCES/EPERM 拒绝、文件模式拒绝与不扩大授权的断言。
- 真实 Chat Mode read_file 尝试打开测试者自己创建、权限为 000 的临时文件：服务按预期返回 Permission denied，未返回文件内容；测试文件已恢复权限并清除。
- **这不是原生 macOS TCC 拒绝证明**：没有访问系统隐私目录，没有使用 tccutil，没有调高 TCC 权限，没有假报真实 TCC 来源。需要用户事先选择并授权可测试的 TCC 受保护测试资源，然后通过真实 Chat Mode 文件读取返回权限拒绝，才可核销 A4-TCC。

## 版本及生产运行门禁（2026-10-21，AEDT）

| 对象 | 已验证版本/状态 | 结论 |
| --- | --- | --- |
| GitHub 受保护 master | b63e47cf，CI/CodeQL 成功 | 当前源码基线 |
| Mac MCP 服务 | ab60a33e，开发热重载运行中 | 已落后于 master |
| 主 Pi MCP 服务 | ab60a33e，开发热重载运行中 | 已落后于 master |
| Sextant MCP 服务 | ab60a33e，开发热重载运行中 | 已落后于 master |
| Mac Jobs Manager | 278af9c，认证的 quiet 接口为 running=1、UNKNOWN=0 | 不满足中断性升级窗口 |
| 主 Pi/Sextant Doctor | 各 31 OK / 2 WARN（配置全量捕获键、ripgrep 版本） | 服务运行，但版本/配置仍需收敛 |

RELEASE-CONVERGE 仍为 EXTERNAL。升级需要独立部署源 SHA、兼容性检查、已运行 Jobs 与活动开发收敛、准确的空闲门禁、回滚方案及重新核实 Chat Mode 连通性。不得为了清空任务清单而强制终止在跑的任务、重启服务或覆写生产主仓库。

Issue #30 的日志归档及生产 prune 是另一会话的独占工作，仍不包含在本验收中。Work Mode 不在本项目目标范围。

## 最终结论

E1-CHAT 按实际六工具配置已获真实客户端证据并核销；A4-TCC 的真实系统拒绝与 RELEASE-CONVERGE 的安全部署仍需外部条件。文档验收、单元测试、MCP 客户端调用、代码合并以及生产运行是不同层次，不相互替代。
