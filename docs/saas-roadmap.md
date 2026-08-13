# Riverline SaaS 路线图

## 1. 结论

Riverline 可以包装为 SaaS，但应把 **扑克规则、事件流、Advisor、Range Belief 和复盘投影保持为独立领域内核**，在边界外逐步增加身份、租户、配额、计费和托管能力。不要为多租户过早改写已验证的规则与恢复链。

建议顺序：

```text
本地 MVP
  → 托管单租户 Alpha
  → 多租户封闭 Beta
  → 付费 SaaS
  → Agent / Solver 扩展平台
```

## 2. 分阶段交付

### S0：本地可体验 MVP

目标：验证核心循环是否值得继续投入。

- 连续 6-max 对战；
- L0 Advisor、公开 Range Belief、session stats；
- 自动复盘和重连；
- 收集体验数据：完成率、决策延迟、复盘打开率、错误复发率；
- 不加入账户、支付、组织或复杂部署抽象。

出口：至少一批真实用户能连续完成牌局，且没有规则、金额、隐私或恢复 P0/P1。

### S1：托管单租户 Alpha

目标：先证明“云上稳定可用”，暂不承担完整多租户复杂度。

- 前端、API、worker 容器化部署；
- PostgreSQL 替代本地 SQLite；
- Redis 只用于异步重分析、Agent 和未来 Solver 作业；
- HTTPS、托管密钥、结构化日志、错误追踪、健康检查；
- 最小用户登录和单用户数据归属；
- 每日备份、恢复演练、部署回滚；
- 禁止公开真钱游戏、用户间资金结算或博彩撮合。

出口：持续运行、备份恢复和发布回滚通过；单用户数据无串读。

### S2：多租户封闭 Beta

目标：建立可审计的数据隔离和成本控制。

- `tenant_id`/`user_id` 进入所有 session、hand、event、projection、review、job 和 artifact；
- API 授权由服务端从身份上下文派生，客户端不能指定任意 hero/tenant；
- PostgreSQL 行级隔离策略或等价 repository 强制过滤；
- 组织、成员、角色与审计日志；
- 限流、并发配额、存储配额和任务预算；
- 对象存储保存大型 solver artifact、导出和备份；
- 用户数据导出、删除和保留期策略；
- 租户隔离、私牌权限和恢复一致性的专用攻击测试。

出口：跨租户访问测试为零泄漏；资源滥用不会影响其他租户。

### S3：付费 SaaS

目标：在稳定使用数据之后加入商业闭环。

- Free / Pro / Coach 等 entitlement，而不是在业务代码中散落套餐判断；
- 支付、订阅、账单 webhook 幂等和宽限期；
- 对昂贵能力按使用量计量：equity samples、Agent tokens、Solver seconds、artifact storage；
- 产品分析只采集必要事件，默认不上传私牌原文到第三方分析平台；
- 隐私政策、服务条款、数据处理说明和许可证 NOTICE/SBOM；
- 支持工单、状态页、事故响应、SLO 与成本告警。

出口：收入能够覆盖计算、存储、模型和支持成本；计费失败不损坏牌局数据。

### S4：Agent / Solver 扩展平台

目标：在核心 SaaS 稳定后开放高级能力。

- 版本化 `BotDecisionProvider` / `AdvisorProvider` contract；
- 沙箱、超时、资源预算、合法动作验证和本地降级；
- Provider provenance、artifact fingerprint 和可复现评测；
- BYO API Key 使用独立 secret vault，不写入事件 payload 或日志；
- 第三方 Provider/策略包先做许可、隐私和安全审核，再允许共享。

## 3. 推荐目标架构

```text
Browser / Mobile Web
        ↓ HTTPS
Web/API Gateway ── Identity / Entitlements / Rate Limits
        ↓
Riverline Application Services
        ├─ Poker authoritative core
        ├─ Advisor / Belief / Stats
        └─ Review / Training
        ↓                 ↓
PostgreSQL           Async Job Queue
 events + projections    ↓
        ↓            Agent/Solver workers
Object Storage      Provider gateways
```

同步路径只执行规则、合法动作、L0 建议和必要读模型；L1/L2/L3、深度解释和批量复盘异步完成并渐进显示。

## 4. SaaS 必须新增的数据边界

建议新增：

- `users`、`organizations`、`memberships`；
- `entitlements`、`usage_meters`、`billing_accounts`；
- `audit_events`、`data_exports`、`deletion_requests`；
- 所有扑克事实表增加不可为空的 owner/tenant 归属；
- Provider credentials 只保存 secret reference，不保存明文。

需要保持不变：

- PokerKit/规则适配层仍是规则真相；
- durable event stream 仍是牌局事实；
- projection 可重建；
- Advisor/Range/Review 必须保留时间语义、来源和 unavailable；
- 对手私牌永不进入 Hero/public projection。

## 5. 成本与套餐原则

- L0 和基础 Bot 成本稳定，可进入免费层；
- equity sampling、外部 Agent、Solver 和长文本解释必须有预算与缓存；
- 以“计算预算和学习能力”区分套餐，不限制用户取回自己的牌局数据；
- 第一阶段避免无限量承诺；先记录真实 P50/P95、缓存命中和每百手成本；
- 外部 Agent/Solver 故障必须降级，不得阻塞用户继续打牌。

## 6. 主要风险

1. **许可证**：AGPL 主仓与所有传递二进制必须有可分发结论、NOTICE 和 SBOM；非商用不豁免义务。
2. **隐私**：私牌、API Key、行为画像和学习记录均为敏感数据；日志与第三方分析必须最小化。
3. **越权**：session ID/hand ID 不能成为授权凭证；所有读取必须从服务端身份派生 owner/hero。
4. **成本失控**：Agent/Solver 需要额度、超时、缓存、排队和降级。
5. **博彩边界**：产品定位保持训练模拟器；不提供真钱桌、资金托管、撮合或收益承诺。
6. **伪精确**：任何 heuristic 或 Agent 解释不得包装为 Solver/GTO 或精确 EV loss。

## 7. 推荐的下一轮工程顺序

1. 先邀请用户体验本地 MVP，收集 100–500 手真实使用反馈；
2. 修复只影响规则、金额、隐私、恢复和核心循环的 P0/P1；
3. 完成依赖 SBOM/NOTICE，建立可重复许可门；
4. 建立 PostgreSQL 单租户托管环境、备份和恢复演练；
5. 加入最小身份归属，再做多租户设计；
6. 用真实延迟与成本数据决定 L1/L2/Solver/Agent 的套餐边界；
7. 最后接入支付，而不是先做计费再验证训练价值。

## 8. SaaS Alpha 验收指标

- 核心牌局成功率、非法行动率、筹码守恒；
- L0 建议 P95、API P95、重连恢复时间；
- 对手私牌和跨租户泄漏为零；
- 每百手数据库、队列、Agent/Solver 成本；
- 自动复盘生成率与打开率；
- 无提示正确率、错误复发率和提示依赖度变化；
- 备份恢复 RPO/RTO 与发布回滚时间。
