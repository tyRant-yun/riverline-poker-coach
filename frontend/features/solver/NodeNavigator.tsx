// Node navigation boundary. The backend currently returns exactly two nodes
// (OOP root + IP response); this renders that data honestly and marks the
// boundary for future multi-node trees — no fabricated nodes.

import type { SolverNodePayload } from "../../types/api";
import { actionLabel } from "../../lib/solver/aggregate";

type Props = {
  root: SolverNodePayload | null | undefined;
  responseNode: SolverNodePayload | null | undefined;
};

export default function NodeNavigator({ root, responseNode }: Props) {
  return (
    <div className="node-navigator" aria-label="solver node tree">
      <div className="node-navigator__row">
        <span className="node-navigator__tag node-navigator__tag--oop">OOP · P{root?.player ?? "?"}</span>
        <span className="node-navigator__actions">
          {(root?.actions ?? []).map((action) => (
            <span className="node-chip" key={action}>
              {actionLabel(action)}
            </span>
          ))}
          {!root?.actions.length && <span className="muted small">—</span>}
        </span>
      </div>
      <div className="node-navigator__edge" aria-hidden="true">
        ↓
      </div>
      <div className="node-navigator__row">
        <span className="node-navigator__tag node-navigator__tag--ip">IP · P{responseNode?.player ?? "?"}</span>
        <span className="node-navigator__actions">
          {(responseNode?.actions ?? []).map((action) => (
            <span className="node-chip" key={action}>
              {actionLabel(action)}
            </span>
          ))}
          {!responseNode?.actions.length && <span className="muted small">—</span>}
        </span>
      </div>
      <p className="muted small node-navigator__note">
        当前结果包含 OOP 决策节点与首个行动的 IP 响应节点。完整节点树将在后端返回多节点结果后启用。
      </p>
    </div>
  );
}
