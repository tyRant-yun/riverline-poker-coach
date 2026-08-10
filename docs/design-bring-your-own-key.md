# 设计：用户自带 DeepSeek API Key 唤醒教学 Agent（端到端加密）

版本：draft-1 · 日期：2026-08-10 · 状态：设计草案（未实现，待评审）

## 1. 需求

- 产品用户**自行配置自己的 DeepSeek API Key** 来唤醒（启用）教学 Agent，而不是由部署方统一提供密钥。
- 密钥**端到端加密**：服务器运营方不应能读取明文密钥；密钥不应以明文落盘、不应进日志。
- 每个用户独立生效（匿名本地用户即可，无需正式账户体系）。
- 复用现有证据约束管线：无论密钥从哪来，教学输出仍必须经过非法行动过滤、证据引用净化和失败降级（`coach/external.py`）。

## 2. 现状（已具备的接缝）

| 能力 | 现状 |
|---|---|
| DeepSeek 兼容 | `ExternalModelTeacher` 走 OpenAI 兼容 `/chat/completions`；设 `POKER_COACH_LLM_BASE_URL=https://api.deepseek.com/v1` + `POKER_COACH_LLM_MODEL=deepseek-chat` 即可，**无需改代码**（本轮已把该配置写进 `.env.example`） |
| 输出净化 | `_sanitize_response` 已独立于传输层，可复用于"浏览器直连"返回的原始输出 |
| 用户态 | 已有匿名 `learning_profiles`（SQLite/PostgreSQL 均可存密文） |
| 前端 | Next.js 编辑器已有教学面板，可加"API Key 设置"入口 |

## 3. 两条路线

### 路线 A：浏览器直连（真 E2E，推荐优先验证）

```text
浏览器持有用户 Key（Web Crypto 派生，永不落服务器）
  → 前端直接调用 https://api.deepseek.com/v1/chat/completions
  → 拿到模型原始 JSON 输出
  → 提交 POST /v1/teaching/raw  { rawModelOutput, scenarioHash, depth }
  → 服务端只做净化（合法动作过滤、证据引用校验、降级）→ TeachingResponse
```

- 密钥**永不出浏览器**，服务器只收"模型原始输出"并做证据绑定——服务器见不到 key，也无法伪造证据。
- 浏览器侧仍需构建 facts 提示词：可新增 `GET /v1/teaching/prompt` 返回只读 facts（与现有 `_build_facts` 同源），前端拼 system+user 消息。
- **前置验证（spike）**：DeepSeek API 是否允许浏览器 CORS 直连（`Access-Control-Allow-Origin`）。若允许 → 路线 A 成立；若不允许（如 OpenAI 那样）→ 需要自建无密钥代理或走路线 B。
- 风险：Key 暴露于浏览器开发者工具可见范围（这是 BYO-key 的固有属性——用户自己的 key，可接受；需在 UI 明示"仅存于本浏览器"）。

### 路线 B：信封加密（服务器瞬时使用，兼容无 CORS 场景）

```text
用户输入密码（或生成随机口令）→ 浏览器用 Web Crypto（PBKDF2/Argon2 派生 AES-GCM 密钥）
  → 加密 DeepSeek Key → 密文随 profile 存服务器
  → 教学请求时浏览器把口令交给服务器（仅当次请求，TLS 内）
  → 服务器内存中派生密钥、瞬时解密、调用 DeepSeek、调用后立即清零
```

- 密钥**静态加密**（服务器只见密文），使用时仅存在于内存，明文不落盘、不进日志。
- 不是严格意义的 E2E（服务器在调用瞬间可解密）——但满足"运营方无法离线读取密钥"的威胁模型；若用户连调用瞬间都不想暴露给服务器，则必须路线 A。
- 需要：`POST /v1/profiles/{id}/llm-key`（收密文+派生参数）、请求头/体携带一次性口令的通道设计、密钥轮换与删除。

## 4. 两种路线共同的设计要点

1. **证据边界不变**：无论哪条路线，`TeachingResponse` 的净化与校验都在服务端执行（`_sanitize_response` + `validate_evidence_references`），模型原始输出不能绕过。
2. **不记录密钥**：审计日志字段（`requestId`、`scenarioHash`、`provider`、`degraded`）不含 key；`POKER_COACH_LLM_*` 服务端全局配置仍保留（部署方统一密钥模式），与 BYO-key 并行。
3. **限额与防滥用**：BYO-key 场景下用户自带配额（DeepSeek 侧计费），服务器仍需限流（现有 `rate_limit_per_minute`）；`/v1/teaching/raw` 请求体大小上限沿用 `max_request_bytes`。
4. **密钥生命周期**：设置、覆盖、删除（删除 profile 时同步删除密文，已有 `delete_profile`）；用户可在前端"清除本机 Key"。
5. **提示词注入边界**：facts 提示词仍由服务端生成（`GET /v1/teaching/prompt` 只读），用户自由文本只进 user 消息（现状不变）。

## 5. 实施顺序（待评审后）

1. **Spike 1（决定路线）**：浏览器 fetch 直连 DeepSeek 验证 CORS（10 分钟，无需改代码）。
   - CORS 允许 → 路线 A；不允许 → 路线 B。
2. **路线 A 落地**：`GET /v1/teaching/prompt`（只读 facts）+ `POST /v1/teaching/raw`（净化入口）+ 前端 Key 设置面板（`localStorage`/IndexedDB 持 key）+ groundedness 测试（复用 `test_external_teacher.py` 的净化断言）。
3. **路线 B 落地（如需）**：Web Crypto 加密 util + profile 密文存储 + 瞬时解密调用链 + 密钥轮换/删除测试。
4. 文档：把本草案更新为最终设计并加入安全边界文档。

## 6. 安全边界（明确不做）

- 服务器不存任何明文 Key（路线 A 根本接触不到；路线 B 只存 AES-GCM 密文）。
- 不在日志、异常消息或 API 响应中回显 Key 或口令。
- 不把 BYO-key 与正式账户/支付绑定；匿名用户即可使用。
- 不绕过 `_sanitize_response`：模型原始输出若无法通过证据校验，一律降级本地教师。
