"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type PointerEvent } from "react";
import { Paperclip, X } from "lucide-react";
import type { Asset, Comment, Deploy, Region, RequestRow, Revision, Run } from "@/lib/types";

type CommentWithRevisionNumber = Comment & { revision_number: number | null };

type StatusResponse = {
  request: RequestRow;
  tenant: { name: string; slug: string } | null;
  revisions: Revision[];
  revision: Revision | null;
  run: Run | null;
  assets: (Asset & { plate_url: string | null; render_url: string | null })[];
  comments: CommentWithRevisionNumber[];
  deployRun: Run | null;
  deploy: (Deploy & { recording_url: string | null }) | null;
};

type EditComment = { canvas_name: string; region: Region; body: string; author?: string };
type EditRequestFile = { kind?: "edit"; comments?: EditComment[] };

const TERMINAL_RUN_STATUSES = new Set(["succeeded", "failed", "crashed"]);
const POLL_INTERVAL_MS = 2000;
const MIN_DRAG_PX = 8; // below this, treat a pointer down/up as a "click", not a drag

// Polling stops only once BOTH the generate/edit run and any in-flight
// deploy run have reached a terminal state - a deploy fired while the
// generate/edit side is already done must still keep the poll alive on its
// own.
function isSettled(json: { run: Run | null; deployRun: Run | null }): boolean {
  const runDone = !json.run || TERMINAL_RUN_STATUSES.has(json.run.status);
  const deployDone = !json.deployRun || TERMINAL_RUN_STATUSES.has(json.deployRun.status);
  return runDone && deployDone;
}

export default function RequestDetailPage() {
  const params = useParams<{ requestId: string }>();
  const requestId = params.requestId;

  const [data, setData] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedCanvas, setSelectedCanvas] = useState<string | null>(null);
  const [hideOlder, setHideOlder] = useState(true);

  const [draftRegion, setDraftRegion] = useState<Region | null>(null);
  const [draftScreenRect, setDraftScreenRect] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  const [commentBody, setCommentBody] = useState("");
  const [editSubmitting, setEditSubmitting] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [deploySubmitting, setDeploySubmitting] = useState(false);
  const [deployError, setDeployError] = useState<string | null>(null);
  const [stoppingRunId, setStoppingRunId] = useState<string | null>(null);

  const imgRef = useRef<HTMLImageElement>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const res = await fetch(`/api/requests/${requestId}`, { cache: "no-store" });
        const json = await res.json();
        if (cancelled) return;
        if (!res.ok) {
          setError(json.error ?? "failed to load");
          return;
        }
        setError(null);
        setData(json as StatusResponse);
        setSelectedCanvas((prev) => prev ?? json.request?.canvases?.[0]?.name ?? null);
        if (isSettled(json) && timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    }

    poll();
    timerRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestId]);

  function restartPolling() {
    if (timerRef.current) return;
    timerRef.current = setInterval(async () => {
      const r = await fetch(`/api/requests/${requestId}`, { cache: "no-store" });
      const j = await r.json();
      setData(j);
      if (isSettled(j) && timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }, POLL_INTERVAL_MS);
  }

  const currentAsset = useMemo(
    () => data?.assets.find((a) => a.canvas_name === selectedCanvas) ?? null,
    [data, selectedCanvas]
  );

  const visibleComments = useMemo(() => {
    if (!data) return [];
    const latestNumber = data.revision?.revision_number ?? null;
    return data.comments.filter((c) => (hideOlder ? c.revision_number === latestNumber : true));
  }, [data, hideOlder]);

  const pinsOnCurrentCanvas = useMemo(
    () => visibleComments.filter((c) => c.canvas_name === selectedCanvas),
    [visibleComments, selectedCanvas]
  );

  function clearDraft() {
    setDraftRegion(null);
    setDraftScreenRect(null);
    setCommentBody("");
    dragStart.current = null;
  }

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    if (!currentAsset?.render_url || !imgRef.current) return;
    const rect = imgRef.current.getBoundingClientRect();
    dragStart.current = { x: e.clientX, y: e.clientY };
    setDraftScreenRect({ left: e.clientX - rect.left, top: e.clientY - rect.top, width: 0, height: 0 });
    setDraftRegion(null);
  }

  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    if (!dragStart.current || !imgRef.current) return;
    const rect = imgRef.current.getBoundingClientRect();
    const x1 = Math.min(dragStart.current.x, e.clientX) - rect.left;
    const y1 = Math.min(dragStart.current.y, e.clientY) - rect.top;
    const x2 = Math.max(dragStart.current.x, e.clientX) - rect.left;
    const y2 = Math.max(dragStart.current.y, e.clientY) - rect.top;
    setDraftScreenRect({
      left: Math.max(0, x1),
      top: Math.max(0, y1),
      width: Math.min(rect.width, x2) - Math.max(0, x1),
      height: Math.min(rect.height, y2) - Math.max(0, y1),
    });
  }

  function onPointerUp(e: PointerEvent<HTMLDivElement>) {
    if (!dragStart.current || !imgRef.current || !currentAsset) return;
    const img = imgRef.current;
    const rect = img.getBoundingClientRect();
    const scaleX = currentAsset.width / rect.width;
    const scaleY = currentAsset.height / rect.height;

    const dx = Math.abs(e.clientX - dragStart.current.x);
    const dy = Math.abs(e.clientY - dragStart.current.y);

    let region: Region;
    if (dx < MIN_DRAG_PX && dy < MIN_DRAG_PX) {
      // A click, not a drag - default to a small area centered on the point.
      const size = Math.round(Math.min(currentAsset.width, currentAsset.height) * 0.08);
      const cx = Math.round((e.clientX - rect.left) * scaleX);
      const cy = Math.round((e.clientY - rect.top) * scaleY);
      region = {
        x: Math.max(0, cx - size / 2),
        y: Math.max(0, cy - size / 2),
        width: size,
        height: size,
      };
    } else {
      const x1 = Math.min(dragStart.current.x, e.clientX) - rect.left;
      const y1 = Math.min(dragStart.current.y, e.clientY) - rect.top;
      const x2 = Math.max(dragStart.current.x, e.clientX) - rect.left;
      const y2 = Math.max(dragStart.current.y, e.clientY) - rect.top;
      region = {
        x: Math.round(x1 * scaleX),
        y: Math.round(y1 * scaleY),
        width: Math.round((x2 - x1) * scaleX),
        height: Math.round((y2 - y1) * scaleY),
      };
    }

    setDraftRegion(region);
    dragStart.current = null;
  }

  async function postComments(comments: EditComment[]) {
    setEditSubmitting(true);
    setEditError(null);
    try {
      const res = await fetch(`/api/requests/${requestId}/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comments }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error ?? "edit failed");
      clearDraft();
      const refreshed = await fetch(`/api/requests/${requestId}`, { cache: "no-store" });
      setData(await refreshed.json());
      restartPolling();
    } catch (err) {
      setEditError(err instanceof Error ? err.message : String(err));
    } finally {
      setEditSubmitting(false);
    }
  }

  async function submitDeploy() {
    if (!selectedCanvas) return;
    setDeploySubmitting(true);
    setDeployError(null);
    try {
      const res = await fetch(`/api/requests/${requestId}/deploy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canvas_name: selectedCanvas }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error ?? "deploy failed");
      const refreshed = await fetch(`/api/requests/${requestId}`, { cache: "no-store" });
      setData(await refreshed.json());
      restartPolling();
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeploySubmitting(false);
    }
  }

  async function submitStop(runId: string) {
    setStoppingRunId(runId);
    try {
      const res = await fetch(`/api/requests/${requestId}/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error ?? "stop failed");
      // Not marked failed instantly - the orchestrator only checks
      // cancel_requested on its own ~15s poll cadence, so keep polling
      // rather than assuming it already happened.
      restartPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStoppingRunId(null);
    }
  }

  function submitDraftComment() {
    if (!draftRegion || !selectedCanvas || !commentBody.trim()) return;
    postComments([{ canvas_name: selectedCanvas, region: draftRegion, body: commentBody, author: "ui" }]);
  }

  async function onUploadEditFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setEditError(null);
    try {
      const parsed = JSON.parse(await file.text()) as EditRequestFile;
      if (!parsed.comments || parsed.comments.length === 0) throw new Error("file has no 'comments' array");
      await postComments(parsed.comments);
    } catch (err) {
      setEditError(`Couldn't parse ${file.name}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  if (error && !data) {
    return (
      <div className="page">
        <p className="error">{error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="page">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  const { request, tenant, revision, run, assets, deployRun, deploy } = data;
  const revisionReady = revision?.status === "ready";
  const deployInFlight = !!deployRun && !TERMINAL_RUN_STATUSES.has(deployRun.status);

  return (
    <div className="workspace">
      <div className="workspace-center">
        <div className="workspace-toolbar">
          <div className="title-block">
            <h1>{request.campaign ?? "(untitled campaign)"}</h1>
            <p className="subtitle">
              {tenant?.name ?? "unknown brand"} · revision {revision?.revision_number ?? "—"}
            </p>
          </div>
          {run && <span className={`status-pill status-${run.status}`}>{run.status}</span>}
        </div>

        <div className="canvas-stage">
          {currentAsset?.render_url ? (
            <div
              className="canvas-stage-inner"
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
            >
              <img ref={imgRef} src={currentAsset.render_url} alt={`${selectedCanvas} render`} draggable={false} />

              {pinsOnCurrentCanvas.map((c, i) => (
                <div
                  key={c.id}
                  className="pin-marker"
                  title={c.body}
                  style={{
                    left: `${((c.region.x + c.region.width / 2) / currentAsset.width) * 100}%`,
                    top: `${((c.region.y + c.region.height / 2) / currentAsset.height) * 100}%`,
                  }}
                >
                  {i + 1}
                </div>
              ))}

              {draftScreenRect && (
                <div
                  className="pin-draft"
                  style={{
                    left: draftScreenRect.left,
                    top: draftScreenRect.top,
                    width: draftScreenRect.width,
                    height: draftScreenRect.height,
                  }}
                />
              )}
            </div>
          ) : (
            <p className="muted">
              {run && !TERMINAL_RUN_STATUSES.has(run.status)
                ? "Waiting for the agent to render this canvas…"
                : "No render available for this canvas."}
            </p>
          )}
        </div>

        {revisionReady && (
          <p className="pin-hint">Click or drag on the image to pin a comment</p>
        )}

        {assets.length > 0 && (
          <div className="filmstrip">
            {request.canvases.map((c) => {
              const asset = assets.find((a) => a.canvas_name === c.name);
              return (
                <div
                  key={c.name}
                  className={`filmstrip-item ${selectedCanvas === c.name ? "active" : ""}`}
                  onClick={() => {
                    setSelectedCanvas(c.name);
                    clearDraft();
                  }}
                >
                  {asset?.render_url ? (
                    <img src={asset.render_url} alt={c.name} />
                  ) : (
                    <div style={{ height: 56, background: "var(--bg)" }} />
                  )}
                  <div className="label">{c.name}</div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="workspace-side">
        <div className="side-section">
          <h3>Review request</h3>
          {run ? (
            <>
              <span className={`status-pill status-${run.status}`}>{run.status}</span>
              {run.status === "running" && (
                <>
                  {run.sandbox_id && (
                    <p className="muted mono" style={{ marginTop: "0.5rem" }}>
                      sandbox: {run.sandbox_id}
                    </p>
                  )}
                  <button
                    className="secondary"
                    style={{ marginTop: "0.5rem" }}
                    onClick={() => submitStop(run.id)}
                    disabled={stoppingRunId === run.id || run.cancel_requested}
                  >
                    {run.cancel_requested ? "Stopping…" : stoppingRunId === run.id ? "Stopping…" : "Stop"}
                  </button>
                </>
              )}
              {run.status === "failed" && run.error_message && (
                <p className="error" style={{ marginTop: "0.5rem" }}>{run.error_message}</p>
              )}
            </>
          ) : (
            <p className="muted">No run yet.</p>
          )}
          <p className="muted" style={{ marginTop: "0.5rem" }}>
            {visibleComments.filter((c) => c.status === "open").length} open comment(s)
          </p>
        </div>

        <div className="side-section">
          <h3>Deploy</h3>
          {!revisionReady ? (
            <p className="muted">Wait for the current revision to finish before deploying.</p>
          ) : (
            <>
              {/* deployRun/deploy reflect the request's MOST RECENT deploy attempt,
                  which may have been for a different canvas than the one currently
                  selected below - the button always deploys selectedCanvas specifically,
                  and "again" only applies when the most recent attempt was for this
                  same canvas, so it's never ambiguous which one you're about to fire. */}
              <button onClick={submitDeploy} disabled={deploySubmitting || deployInFlight || !selectedCanvas}>
                {deployInFlight
                  ? `Deploying ${deployRun?.canvas_name ?? "…"}`
                  : deploy && deploy.canvas_name === selectedCanvas
                  ? `Deploy ${selectedCanvas} again`
                  : `Deploy ${selectedCanvas ?? "…"}`}
              </button>
              {deployError && <p className="error" style={{ marginTop: "0.5rem" }}>{deployError}</p>}

              {deployRun && (
                <div style={{ marginTop: "0.75rem" }}>
                  <p className="muted mono" style={{ marginBottom: "0.25rem", fontSize: "0.8rem" }}>
                    last deploy attempt: {deployRun.canvas_name ?? "(unknown canvas)"}
                  </p>
                  <span className={`status-pill status-${deployRun.status}`}>{deployRun.status}</span>
                  {deployRun.status === "running" && (
                    <button
                      className="secondary"
                      style={{ marginLeft: "0.5rem" }}
                      onClick={() => submitStop(deployRun.id)}
                      disabled={stoppingRunId === deployRun.id || deployRun.cancel_requested}
                    >
                      {deployRun.cancel_requested || stoppingRunId === deployRun.id ? "Stopping…" : "Stop"}
                    </button>
                  )}
                  {deployRun.status === "failed" && deployRun.error_message && (
                    <p className="error" style={{ marginTop: "0.5rem" }}>{deployRun.error_message}</p>
                  )}
                </div>
              )}

              {deploy && (
                <div style={{ marginTop: "0.75rem" }}>
                  <p className="muted" style={{ marginBottom: "0.25rem" }}>
                    {deploy.verified ? "✓ Verified via Adstream's own detail page" : "Not verified"}
                  </p>
                  {deploy.adstream_ad_name && (
                    <p className="mono" style={{ fontSize: "0.85rem" }}>{deploy.adstream_ad_name}</p>
                  )}
                  {deploy.adstream_url && (
                    <a href={deploy.adstream_url} target="_blank" rel="noreferrer" style={{ fontSize: "0.85rem" }}>
                      {deploy.adstream_url}
                    </a>
                  )}
                  {deploy.recording_url ? (
                    <video
                      src={deploy.recording_url}
                      controls
                      style={{ width: "100%", marginTop: "0.5rem", borderRadius: 6 }}
                    />
                  ) : (
                    <p className="muted" style={{ marginTop: "0.5rem" }}>
                      No recording available — per the brief's own rule, a deploy with no recording
                      is treated as failed regardless of what the browser did.
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {draftRegion && (
          <div className="side-section">
            <h3>New comment</h3>
            <p className="muted mono" style={{ marginBottom: "0.5rem" }}>
              {selectedCanvas} · x={draftRegion.x} y={draftRegion.y} w={draftRegion.width} h={draftRegion.height}
            </p>
            <textarea
              rows={3}
              value={commentBody}
              onChange={(e) => setCommentBody(e.target.value)}
              placeholder="What should change here?"
              style={{ width: "100%" }}
            />
            {editError && <p className="error">{editError}</p>}
            <div className="side-actions" style={{ marginTop: "0.6rem" }}>
              <button onClick={submitDraftComment} disabled={editSubmitting || !commentBody.trim()}>
                {editSubmitting ? "Submitting…" : "Submit"}
              </button>
              <button className="secondary" onClick={clearDraft} disabled={editSubmitting}>
                <X size={15} />
              </button>
            </div>
          </div>
        )}

        <div className="side-section" style={{ flex: 1 }}>
          <h3>Comments</h3>

          <button className="ghost" style={{ marginBottom: "0.5rem" }} onClick={() => fileInputRef.current?.click()}>
            <Paperclip size={14} /> Upload edit-request.json
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json"
            style={{ display: "none" }}
            onChange={onUploadEditFile}
          />

          {visibleComments.length > 0 ? (
            <div className="comment-thread">
              {visibleComments.map((c) => (
                <div className="comment-item" key={c.id}>
                  <div className="comment-meta">
                    <span>
                      {c.canvas_name} · rev {c.revision_number}
                    </span>
                    <span className={`status-pill status-${c.status}`}>{c.status}</span>
                  </div>
                  <div className="comment-body">{c.body}</div>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">No comments yet.</p>
          )}

          <label className="toggle-row">
            <input type="checkbox" checked={hideOlder} onChange={(e) => setHideOlder(e.target.checked)} />
            Hide older revision comments
          </label>
        </div>
      </div>
    </div>
  );
}
