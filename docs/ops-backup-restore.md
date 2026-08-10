# 运维：备份与恢复

日期：2026-08-10 · 状态：✅ 文档化（单人/内网 MVP 够用）

## 数据形态

| 存储 | 位置 | 说明 |
|---|---|---|
| 场景/历史/学习记录（SQLite 默认） | `.data/` 或 `POKER_COACH_DB_PATH` | 单文件，复制即备份 |
| PostgreSQL（compose 部署） | `pgdata` 卷（compose 定义） | 生产形态 |
| Redis | 内存 + 持久化（compose 未启用 AOF） | 作业队列/缓存，**可重建**（分析可重算、求解可重跑） |
| Solver 结果缓存 | SQLite solve_cache / 未来 PG 表 | 可重建（预求解脚本重跑） |

## 备份（SQLite 单机）

```powershell
# 冷备（推荐在服务停止时）
copy .data\poker_coach.db .\backups\poker_coach-<date>.db
# 热备（SQLite 在线备份 API）
py -3.13 -c "import sqlite3; src=sqlite3.connect('.data/poker_coach.db'); dst=sqlite3.connect('backup.db'); src.backup(dst); dst.close(); src.close()"
```

## 备份（PostgreSQL / compose）

```bash
docker exec poker-coach-postgres-1 pg_dump -U coach -d coach | gzip > backups/coach-$(date +%F).sql.gz
```

## 恢复

- SQLite：替换数据库文件后重启 api。
- PG：`gunzip -c backup.sql.gz | docker exec -i poker-coach-postgres-1 psql -U coach -d coach`。
- Redis：无需备份（队列空转；重新分析/求解即可重建产物）。

## 建议频率

- 开发期：每次"阶段封口"提交前冷备 SQLite 一次。
- 部署期：pg_dump 每日 cron（见 CI/运维自动化待办）。

## 待补（非阻塞）

- compose 启用 Redis AOF（`appendonly yes`）——作业结果幂等可重算，优先级低。
- 备份脚本 `scripts/backup.ps1` 一键执行上表命令。
