"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { continuousTableApi } from "../../lib/api/client";
import type { TableReviewResponse } from "../../types/api";

const sessionStorageKey = "riverline-continuous-table-session";

export default function TableReviewsPanel() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [list, setList] = useState<NonNullable<TableReviewResponse["reviews"]> | null>(null);
  const [review, setReview] = useState<TableReviewResponse["review"] | null>(null);
  const [message, setMessage] = useState("正在读取复盘…");
  const request = useRef(0);

  const loadList = useCallback(async (nextSessionId: string | null) => {
    const token = ++request.current;
    setReview(null);
    if (!nextSessionId) {
      setList(null);
      setMessage("尚未开始牌桌，完成一手后可在这里查看复盘。");
      return;
    }
    setMessage("正在读取复盘…");
    try {
      const response = await continuousTableApi.reviews(nextSessionId);
      if (token !== request.current) return;
      if (!response.available) {
        setList(null);
        setMessage(`复盘未就绪${response.unavailableReason ? `：${response.unavailableReason}` : ""}`);
        return;
      }
      const reviews = response.reviews ?? (response.review ? [{ handId: response.review.handId }] : []);
      setList(reviews);
      setMessage(reviews.length ? "选择一手查看已记录的 Hero 决策。" : "尚无已完成手牌可复盘。");
    } catch {
      if (token === request.current) {
        setList(null);
        setMessage("复盘未就绪：无法连接本地后端。");
      }
    }
  }, []);

  useEffect(() => {
    const storedSessionId = window.localStorage.getItem(sessionStorageKey);
    setSessionId(storedSessionId);
    void loadList(storedSessionId);
    return () => { request.current += 1; };
  }, [loadList]);

  async function openReview(handId: string) {
    if (!sessionId) return;
    const token = ++request.current;
    setReview(null);
    setMessage("正在读取复盘…");
    try {
      const response = await continuousTableApi.reviews(sessionId, handId);
      if (token !== request.current) return;
      if (response.available && response.review?.handId === handId) {
        setReview(response.review);
        setMessage("");
      } else {
        setMessage(`复盘未就绪${response.unavailableReason ? `：${response.unavailableReason}` : ""}`);
      }
    } catch {
      if (token === request.current) setMessage("复盘未就绪：无法连接本地后端。");
    }
  }

  return (
    <section className="review-list" data-testid="table-reviews-panel">
      <div className="panel-heading"><div><h2>复盘</h2><p>仅显示当前本地牌桌会话中已完成的手牌与 Hero 决策。</p></div>
        <button type="button" onClick={() => void loadList(sessionId)}>刷新</button>
      </div>
      {list && <ol className="review-list__hands">{list.map(({ handId }) => <li key={handId}><button type="button" onClick={() => void openReview(handId)}>{handId}</button></li>)}</ol>}
      {message && <p className="muted" role="status">{message}</p>}
      {review && <section className="notice" data-testid="selected-table-review"><strong>手牌 {review.handId}</strong><p>Hero 决策：{review.heroDecisions.length}</p>
        {review.heroDecisions.length > 0 && <ol>{review.heroDecisions.map((decision) => <li key={decision.actionSequence}>{decision.street} · {decision.action}</li>)}</ol>}
        <p className="muted small">来源引用按可用性呈现；此视图不提供对手私牌或深度分析。</p>
      </section>}
    </section>
  );
}
