# Binnacle Job Awareness — R2 第二轮调查总结

**调查结论：本地五组实验完成；真实 ChatGPT E1/E2 未执行；整体 INCONCLUSIVE，暂不批准功能实现或生产部署。**
日期：2026 年 10 月 10 日（澳大利亚悉尼）
Supervisor：本 ChatGPT 协调会话，只读复核各 Worker 的原始结果，不替代 Worker 编造或修改测试证据。

## 一、调查范围和可追溯版本

本文件是 R2 本地五组实验结束后的正式 Supervisor 结果报告；它**不改变**已冻结于 R2 原始提交 cc386613a20f14cd466f19d0fbd3e38ec6ce9927 的测试输入、模型分配或验收准则。原始结果与哈希索引保存在 Raspberry Pi；GitHub 保留可审阅的完整结论。

本报告引用的所有本地 Worker 证据均经过独立结构/哈希校验。E1/E2 真实 ChatGPT Chat 实验未获批准的独立测试 App 连接，因此仍未执行。

R1 第一轮结束后，用户要求先提交正式结果文档，再完善 R2 计划，并以本地 Codex 并行执行。R1 正式结果：[R1-INVESTIGATION-RESULTS.md](https://github.com/grammy-jiang/binnacle/blob/50cca28695dce8b2f11810b92aa792179b0e9eb4/docs/job-awareness-feasibility/R1-INVESTIGATION-RESULTS.md)，已提交至研究分支，commit 50cca28695dce8b2f11810b92aa792179b0e9eb4。

R2 正式计划原始提交 cc386613a20f14cd466f19d0fbd3e38ec6ce9927；后续研究分支 759e499 等提交只增加 R1 链接与 R2 报告材料，不改变**已冻结的执行合同**。

- R2 Run ID：R2-20261010-191506-889bdb8e
- 产品源码 SHA：d61761356ee0fce8ea6d73b0c3043b4881c5645e
- R1 文档 SHA：62a677b83f5b3a34dddc7fd23595f00ffe89159a
- R1 fixture SHA：e1c35bda430a2e8e3794d51032cf827afec7bfa451887731918b7fd529970d41
- R2 原计划 SHA：cc386613a20f14cd466f19d0fbd3e38ec6ce9927
- R2 fixture SHA：74c97e6d1b35f86be8484560d4cbb3f7a56090ceaa87da4303a206771016847e
- 原始证据目录（仍保留在 Raspberry Pi，而非 GitHub）：/home/grammy-jiang/Projects/binnacle-job-awareness-r2-results/R2-20261010-191506-889bdb8e
- 只读原始证据校验：supervisor/validate_r2_evidence.py
- 完整校验结果：supervisor/collection-report.json
- 形式化门禁结论：supervisor/decision.json
- 证据冲突与局限：supervisor/contradictions.md
- 客户端阻碍：supervisor/client-gates.json
- Fixture 语义校验：supervisor/fixture-semantic-audit.json

R2-0 建立 12 个合成 Job、三类候选 Carrier 和各 12 组冻结的 A/B Pair，准备 5 份独立输入包，完全隔离真实 Binnacle 生产任务与连接器。R2-0 状态 PARTIAL，因为真实 ChatGPT Chat 连接尚未验证。五份本地 Worker 的 Model 与 Effort 都有原生运行证据，所有实际执行完毕的证据包均通过结构、哈希、事件和输入一致性验证。

## 二、各工作流最终状态

| 工作流 | 模型、Effort | 结果 | 经过验证的边界 |
| --- | --- | --- | --- |
| A：合成测试服务与 ChatGPT 连接 | Codex gpt-6-sol / medium | **BLOCKED**（A1/A2 PASS，A3/A4 BLOCKED） | 4 个只读合成工具、4 次有效调用、2 个拒绝案例通过；新的真实 ChatGPT 插件、HTTPS/Tunnel 及账户授权未完成 |
| B：可信会话身份与隔离 | Codex gpt-6-astra / xhigh | **INCONCLUSIVE**（B1–B3 PASS，B4 BLOCKED） | 108 次原生 ASGI/FastMCP 合成调用，93 个负例及 15 个实验室授权正例，通过但无法证明真实 ChatGPT Chat 的可信会话身份 |
| C：ACK、Cursor、故障与重放 | Codex gpt-6-astra / xhigh | **INCONCLUSIVE**（C1/C3/C4 PASS，C2 INCONCLUSIVE） | 132 个合成检查通过，显式 ACK 与下一次可信调用携带不透明凭证的方案在实验室中成立；真实客户端确认、TCP 丢包仍未证明 |
| D：真实传输与性能 | Codex gpt-6-astra / high | **INCONCLUSIVE**（D1/D3 BLOCKED，D2 INCONCLUSIVE，D4 PASS） | 42 个本地协议/结构案例通过；最大 hint 119 UTF-8 字节；沙箱 TCP socket EPERM 阻断完整 RPC 延迟量测 |
| E0：ChatGPT A/B 试验准备 | Codex gpt-6-sol / medium | **PASS**（只含离线准备） | 36 组配对测试脚本与账户/Plugin 门禁已准备；真实 ChatGPT 调用次数仍为零 |
| E1：真实 ChatGPT Chat 可见性 | ChatGPT Chat GPT-6 / Medium | **BLOCKED / NOT RUN** | 尚无被批准的独立测试 MCP 插件与经过验证的真实 Chat 客户端 |
| E2：同回合续跑与 3 Chat 隔离 | ChatGPT Chat GPT-6 / Medium | **BLOCKED / NOT RUN** | E1 未通过，B 尚无可信聊天授权绑定，C 缺真实客户端回执 |

**注意：Worker 的 PASS 是“按其可执行的测试场景提供了完整证据”，不等同于 Job Awareness 功能假设已获支持。**

## 三、最重要的技术结论

### 1. 认证身份是上线前的硬性限制

B 在合成环境中验证了严格拒绝未知归属和签名授权的逻辑；但已检查的 Binnacle 源码识别的是共用 tunnel client/principal，并不提供真实 ChatGPT conversation 对应的认证身份。仅凭客户端名称、请求头、哈希化 session 字段或 Turn ID，**不能安全地将后台 Job 推送给一个特定聊天**。因此自动 per-chat Job Awareness 暂无生产授权前提。

### 2. 当前“读取 Job 结果就自动确认”的假设仍被否定

R1 W3 已证明服务端成功返回或 Cursor 前进，不代表客户端完整接收。R2 C 在更独立的合成持久化/故障环境中确认：具备真实消费者身份时，可以用单独显式 ACK，或者在后续可信调用中提交不透明、不可伪造的分页证明，避免误确认且保留 Job 输出。两种方案的 **SUPPORTED 仅限实验室**；它们没有成为 Binnacle 正式 API，也未证明 ChatGPT 会返回证明材料。

现阶段**最保守的设计候选是显式、消费者绑定的 ACK**；是否选择它需要真实 MCP/ChatGPT 兼容性、身份权限与额外调用成本验证。

### 3. 元数据到模型的可见性依然没有端到端证据

A 的本地 synthetic FastMCP Client 可以接收 nonce，证明了本地服务接口；D 验证了一部分原生工具结果/错误契约。但**没有一个 R2 Worker 证明真正的 ChatGPT Chat 模型能看到 _meta 提醒并自动调用结果工具**。已结束的聊天无法被被动 MCP 响应唤醒，这是另一项明确的产品限制。

### 4. 完整传输与性能不能通过沙箱失败来推断

D 的 TCP socket creation 遭系统沙箱以 EPERM 拒绝，因此本轮没有可审计的 TCP 全路径 P50/P95/P99 或 HTTPS/Tunnel 结果。它完成的本地有效载荷和 token 统计不能替代最终用户体验性能。不得为了测试便利绕过安全沙箱。

D 还记录一个具体协议风险：合成无效 structured payload 即使违反独立 JSON Schema 检查，原生结果仍可呈现为 isError=false 的成功形态。任何提醒中间件都不能擅自将这种无效结果视为有效成功响应；需要正式实现时补充完整验证。

### 5. 新发现：测试数据自身存在语义缺陷

本轮的全部 12 个合成 Job 中，fixture-manifest.json 声明的 nonce_sha256 **均不等于实际 visible nonce 字符串的 SHA-256**（12/12 错误）。文件整体 SHA/输入包 SHA 是正确的，说明数据没有被篡改；错误在生成数据时的字段语义。B 的 Job 归属和权限负例使用的是 job ID/owner，与此缺陷不同，因此可以保留其范围内的观察。

然而 E1 的 nonce 可见性验证绝不能直接使用这些错误的 hash 字段。应为下一次真实 ChatGPT 测试生成**新 Run ID、新版 fixture**，独立逐项验证 nonce SHA，不可修补旧的封存输入并假称仍是同一基线。

## 四、形式化 G0–G7 门禁

| Gate | Verdict | 主要原因 |
| --- | --- | --- |
| G0 输入与运行隔离 | **FAIL（数据语义）** | 原始 SHA 校验通过，但 12/12 nonce 字段语义不正确，不能用作可信客户端 nonce 测试 |
| G1 原生结果与完整传输 | INCONCLUSIVE | 本地部分可行，外部 TCP/TLS/真实 ChatGPT 接收未验 |
| G2 Chat 模型可见性 | BLOCKED | 没有真实 ChatGPT Chat 测试 App 工具调用 |
| G3 可信 per-chat 隔离 | INCONCLUSIVE | 实验室零泄漏，但缺少真实认证 conversation identity |
| G4 结果确认与重放 | INCONCLUSIVE | 实验室新回执方案可行，真实客户端确认未证明；旧隐式 ACK 已否定 |
| G5 性能和 Token 开销 | BLOCKED | TCP 沙箱拒绝，全路径时延缺失 |
| G6 同回合工作连续性 | BLOCKED | 没有真实 ChatGPT Chat A/B 实验 |
| G7 正式工具与错误兼容性 | INCONCLUSIVE | 缺乏完整客户端回归；存在 success-shaped invalid STRUCT 的实验室负面观察 |

综合决定：**INCONCLUSIVE**。这里的 G0 FAIL 代表该版本输入用于客户端 nonce 验证的完整性不合格，不代表 Job Awareness 产品概念已经被证明不可能。

**生产权限：没有。** 不能合并、发布、部署 Job Awareness，也不能把本地实验结果宣布为生产功能。

## 五、下一轮需要完成的明确工作

1. **修正输入生成和验证：** 在一个新的、有来源证明的 Run ID 中生成 nonce；以真实客户端将收到的 nonce 原文计算 SHA-256，逐项验证，再冻结新输入。这是 E1 前的必要条件。旧 R2 数据不得改动。
2. **确认 ChatGPT App 接入权限：** 由得到明确授权的用户/界面操作员在 ChatGPT Chat 添加隔离的只读合成 MCP Plugin，使用单独的 HTTPS 服务或已批准的 Secure MCP Tunnel，并验证目标 App 及 GPT-6/Medium 选择。不能使用生产 Binnacle 连接器或 Codex Desktop 替代。
3. **可信身份方案：** 证明 per-chat 可认证授权来源；若真实 Chat 平台不提供，则只探索有明确授权边界的较窄作用域，保持无凭证时 fail-closed。
4. **完成回执真实互通：** 在前述认证绑定基础上验证显式 ACK 或下一次可信调用中的不透明证明，处理丢失响应、重复/分页/重启与 durable output replay。绝不使用旧的 server-fetch-only ACK。
5. **独立合规的 TCP 性能补测：** 必须在确实允许独立 loopback TCP 的合法受控测试环境中进行，不绕过当前 Codex/OS 的安全拒绝；否则继续标注未测。
6. **E1/E2 实际 Chat 模式行为实验：** 用通过前述门禁的新版合成数据先做一次可见性 canary，再进行 12 组配对、三会话隔离、真实结果读取和同回合有意义的后续工具调用。

## 六、结束状态与完整性保护

五个本地 R2 Worker 的原始输出均已结束，Supervisor 验证器五组全部显示 structural_status=PASS（其中 A 的整体业务状态仍 BLOCKED，B/C/D INCONCLUSIVE，E0 PASS）。两处 Worker 事件关联缺失已经分别交回原工作流的 Codex Agent 做了最小可信补证，没有更改其技术结论。

E1/E2 没有获授权建立连接，因此真实客户端实验仍处 BLOCKED。不得伪称该两组已经结束并 PASS。

**R2 本地调查与结果文档已完成；Job Awareness 全部前置研究尚未完成，当前总体结论 INCONCLUSIVE。** 原始 R1/R2 证据保持可追溯，R1、R2 的源码和测试输出互不覆盖；生产 MCP、Job Manager 服务未因本次研究而改动。
