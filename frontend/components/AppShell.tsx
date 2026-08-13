// App shell: top navigation + status. The workspace views are composed by
// the page; this component owns only chrome.

import type { ReactNode } from "react";

export type WorkspaceView = "table" | "reviews";

const VIEWS: { id: WorkspaceView; label: string }[] = [
  { id: "table", label: "牌桌" },
  { id: "reviews", label: "复盘" },
];

export type HealthStatus = "loading" | "online" | "offline";

type Props = {
  activeView: WorkspaceView;
  onViewChange: (view: WorkspaceView) => void;
  healthStatus: HealthStatus;
  onRetryHealth: () => void;
  children: ReactNode;
};

export default function AppShell({ activeView, onViewChange, healthStatus, onRetryHealth, children }: Props) {
  return (
    <div className="app">
      <header className="app-header">
        <div className="app-brand">
          <span className="app-brand__mark" aria-hidden="true">
            ♠
          </span>
          <span className="app-brand__name">Riverline</span>
        </div>
        <nav className="app-nav" aria-label="工作区">
          {VIEWS.map((view) => (
            <button
              key={view.id}
              className={`app-nav__tab ${activeView === view.id ? "app-nav__tab--active" : ""}`}
              onClick={() => onViewChange(view.id)}
              aria-current={activeView === view.id ? "page" : undefined}
            >
              {view.label}
            </button>
          ))}
        </nav>
        <div className={`status-pill status-pill--${healthStatus}`} data-testid="health-status">
          <span className="pulse" />
          {healthStatus === "loading" ? "服务状态：检查中" : healthStatus === "online" ? "服务状态：在线" : "服务状态：离线"}
          {healthStatus === "offline" && <button type="button" className="status-pill__retry" onClick={onRetryHealth}>重试</button>}
        </div>
      </header>
      <main className="shell">{children}</main>
    </div>
  );
}
