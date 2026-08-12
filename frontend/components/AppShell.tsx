// App shell: top navigation + status. The workspace views are composed by
// the page; this component owns only chrome.

import type { ReactNode } from "react";

export type WorkspaceView = "handlab" | "table" | "solver" | "train" | "library";

const VIEWS: { id: WorkspaceView; label: string }[] = [
  { id: "handlab", label: "Hand Lab" },
  { id: "table", label: "持续牌桌" },
  { id: "solver", label: "Solver" },
  { id: "train", label: "Train" },
  { id: "library", label: "Library" },
];

type Props = {
  activeView: WorkspaceView;
  onViewChange: (view: WorkspaceView) => void;
  children: ReactNode;
};

export default function AppShell({ activeView, onViewChange, children }: Props) {
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
        <div className="status-pill">
          <span className="pulse" />
          本地规则核心在线
        </div>
      </header>
      <main className="shell">{children}</main>
    </div>
  );
}
