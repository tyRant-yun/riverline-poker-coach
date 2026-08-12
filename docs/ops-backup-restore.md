# 运维：备份与恢复

日期：2026-08-10 · 状态：✅ 文档化（单人/内网 MVP 够用）

## 数据形态

| 存储 | 位置 | 说明 |
|---|---|---|
| 场景/历史/学习记录（SQLite 默认） | `.data/` 或 `POKER_COACH_DB_PATH` | 单文件，复制即备份 |
| Authoritative Session/Hand Event/投影/outbox（SQLite MVP） | 部署指定的同一 SQLite 文件 | `game_sessions` 与 `hand_events` 是恢复所需持久数据；projection snapshot/checkpoint 可丢弃重建，outbox 是已提交外部效果意图 |
| PostgreSQL（compose 部署） | `pgdata` 卷（compose 定义） | 生产形态 |
| Redis | 内存 + 持久化（compose 未启用 AOF） | 作业队列/缓存，**可重建**（分析可重算、求解可重跑） |
| Solver 结果缓存 | SQLite solve_cache / 未来 PG 表 | 可重建（预求解脚本重跑） |

## 备份（SQLite 单机）

```powershell
# 冷备（推荐在服务停止时）
copy .data\poker_coach.sqlite3 .\backups\poker_coach-<date>.sqlite3
# 热备（SQLite 在线备份 API）
py -3.13 -c "import sqlite3; src=sqlite3.connect('.data/poker_coach.sqlite3'); dst=sqlite3.connect('backup.sqlite3'); src.backup(dst); dst.close(); src.close()"
```

若部署通过 `POKER_COACH_DB_PATH` 使用其他文件名，上述源路径必须替换为实际值。不要在不同时点分别复制 session、event 或 outbox 表；它们必须来自同一个 SQLite backup snapshot。

## 备份（PostgreSQL / compose）

```bash
docker exec poker-coach-postgres-1 pg_dump -U coach -d coach | gzip > backups/coach-$(date +%F).sql.gz
```

## 恢复

- SQLite：停止 API/outbox/projection writer，保留当前文件的可回退副本，替换数据库文件后重启。恢复后从 `hand_events` 重放并对比 fingerprint；projection snapshot/checkpoint 可显式 discard 后 rebuild。
- PG：`gunzip -c backup.sql.gz | docker exec -i poker-coach-postgres-1 psql -U coach -d coach`。
- Redis：无需备份（队列空转；重新分析/求解即可重建产物）。

## 应用回滚边界

- 回滚前停止新的 session/event 写入与 outbox/projection worker，并先执行数据库备份。
- 只回滚应用代码/镜像；保留 `game_sessions`、`hand_events`、`projection_checkpoints`、`projection_snapshots` 和 `outbox_messages`。旧应用可忽略它不识别的表，不得为回滚代码而删除已提交事实。
- 不执行 Alembic migration downgrade。`0002` downgrade 会删除 `hand_events`，`0003` downgrade 会删除 projection/outbox 恢复状态，都是破坏性操作。
- 回滚后若旧代码不能继续 authoritative session，保持写入停用，直到恢复到兼容版本；不得伪造 snapshot 或跳过 event head。

F1-07 的本地演练使用 SQLite online backup API，并在恢复文件上验证 session snapshot、原始 event JSON、event replay fingerprint、projection discard/rebuild fingerprint 以及已 dispatched outbox 不重复计数。PostgreSQL 只在 `POKER_COACH_TEST_PG_URL` 配置时做 live 演练。

## 建议频率

- 开发期：每次"阶段封口"提交前冷备 SQLite 一次。
- 部署期：pg_dump 每日 cron（见 CI/运维自动化待办）。

## 待补（非阻塞）

- compose 启用 Redis AOF（`appendonly yes`）——作业结果幂等可重算，优先级低。
- 备份脚本 `scripts/backup.ps1` 一键执行上表命令。
