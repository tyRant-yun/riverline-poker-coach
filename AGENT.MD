# Agent 规则兼容入口

本仓库的唯一权威 Agent 执行规则是根目录 [`AGENTS.md`](AGENTS.md)。

任何被旧任务、自动化或 prompt 要求读取 `AGENT.MD` 的 Agent，必须立即完整读取 `AGENTS.md`，并以 `AGENTS.md` 为准；不要把本兼容入口视为已完成规则加载。
