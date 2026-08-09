# 德州扑克策略教学产品

当前状态：阶段 0、阶段 1、阶段 2、阶段 3、阶段 4、阶段 5 和阶段 6 已完成一个可运行切片；阶段 8 已加入 principle-only 教学降级。当前覆盖 HU NLHE 事件重放、合法动作、牌力与牌面分析、精确/模拟 Equity、证据汇总、FastAPI、SQLite 场景历史和 Next.js 场景编辑器。

## 本地验证

后端测试、编译和依赖检查：

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克
python -m pytest
python -m compileall -q backend/poker_coach backend/tests
python -m pip check
```

测试入口从仓库根目录执行，覆盖领域合同、PokerKit 适配层、金标牌谱、回放不变量、分析核心、API、持久化和教学证据绑定。

## 本地启动

启动后端：

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克
python -m uvicorn poker_coach.api.app:app --app-dir backend --reload
```

启动前端（另开终端）：

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克\frontend
npm install
npm run dev
```

前端默认访问 `http://127.0.0.1:8000`；可用 `NEXT_PUBLIC_API_BASE_URL` 覆盖。默认 SQLite 文件位于 `.data/`，不会提交到 Git。

## 工程文档

- [工程基线](docs/engineering-baseline.md)
- [MVP 架构决策](docs/adr/0001-mvp-architecture-decisions.md)
- [依赖与许可证清单](docs/dependency-inventory.md)
- [开发规范](AGENT.MD)

## 当前边界

策略场景库、学习画像、练习系统、PostgreSQL 生产适配、异步分析取消和完整 Agent 模型接入仍未完成。当前教学服务只使用 EvidenceBundle 提供 principle-only 解释；没有可靠策略数据时不会输出虚假 GTO 频率。
