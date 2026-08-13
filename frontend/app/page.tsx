"use client";

import { useCallback, useEffect, useState } from "react";

import AppShell, { type HealthStatus, type WorkspaceView } from "../components/AppShell";
import TableReviewsPanel from "../features/reviews/TableReviewsPanel";
import ContinuousTablePage from "../features/table/ContinuousTablePage";
import { systemApi } from "../lib/api/client";

export default function Home() {
  const [activeView, setActiveView] = useState<WorkspaceView>("table");
  const [healthStatus, setHealthStatus] = useState<HealthStatus>("loading");

  const refreshHealth = useCallback(async () => {
    setHealthStatus("loading");
    try {
      const health = await systemApi.health();
      setHealthStatus(health.status === "ok" ? "online" : "offline");
    } catch {
      setHealthStatus("offline");
    }
  }, []);

  useEffect(() => { void refreshHealth(); }, [refreshHealth]);

  return (
    <AppShell activeView={activeView} onViewChange={setActiveView} healthStatus={healthStatus} onRetryHealth={() => void refreshHealth()}>
      {healthStatus === "offline" && <p className="backend-offline" role="status">启动后端后重试：本地 SQLite 数据保存在本机。</p>}
      {activeView === "table" ? <ContinuousTablePage /> : <TableReviewsPanel />}
    </AppShell>
  );
}
