"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import {
  ArrowUp,
  BarChart3,
  BookOpen,
  History,
  LayoutGrid,
  Paperclip,
  Palette,
  Repeat,
  Sparkles,
  TrendingUp,
  Users,
} from "lucide-react";
import { CANVAS_OPTIONS, type Canvas, type Copy, type Tenant } from "@/lib/types";

type PastRequest = {
  id: string;
  campaign: string | null;
  copy: Copy;
  canvases: Canvas[];
  created_at: string;
};

type NewRequestFile = {
  kind?: "new";
  tenant_slug?: string;
  campaign?: string;
  copy?: Partial<Copy>;
  canvases?: Canvas[];
  inspirations?: string[];
};

const EMPTY_COPY: Copy = {
  eyebrow: "",
  headline: "",
  subhead: "",
  cta: "",
  cta_href: "",
  legal: null,
  brief: null,
};

const CATEGORIES = [
  { label: "Demand gen", icon: TrendingUp },
  { label: "Lifecycle & nurture", icon: Repeat },
  { label: "Audience & data", icon: Users },
  { label: "Creative & content", icon: Sparkles },
  { label: "Analyst", icon: BarChart3 },
];

const STEPS = ["Describe request", "Choose inspiration", "Add details", "Review"];

export default function NewCampaignPage() {
  const router = useRouter();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantId, setTenantId] = useState("");
  const [pastRequests, setPastRequests] = useState<PastRequest[]>([]);
  const [showAllShortcuts, setShowAllShortcuts] = useState(false);

  const [step, setStep] = useState(1);
  const [copy, setCopy] = useState<Copy>(EMPTY_COPY);
  const [campaign, setCampaign] = useState("");
  const [selectedCanvases, setSelectedCanvases] = useState<Set<string>>(
    new Set(CANVAS_OPTIONS.map((c) => c.name))
  );

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch("/api/tenants")
      .then((r) => r.json())
      .then((json) => {
        setTenants(json.tenants ?? []);
        if (json.tenants?.length) setTenantId(json.tenants[0].id);
      })
      .catch(() => setError("Could not load the brand list."));
  }, []);

  useEffect(() => {
    if (!tenantId) return;
    fetch(`/api/requests?tenant_id=${tenantId}&limit=20`)
      .then((r) => r.json())
      .then((json) => setPastRequests(json.requests ?? []))
      .catch(() => setPastRequests([]));
  }, [tenantId]);

  const activeTenant = useMemo(() => tenants.find((t) => t.id === tenantId), [tenants, tenantId]);

  function toggleCanvas(name: string) {
    setSelectedCanvases((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function applyRequestFile(parsed: NewRequestFile) {
    if (parsed.tenant_slug) {
      const match = tenants.find((t) => t.slug === parsed.tenant_slug);
      if (match) setTenantId(match.id);
      else setError(`request.json names tenant_slug '${parsed.tenant_slug}', which isn't onboarded yet.`);
    }
    if (parsed.campaign) setCampaign(parsed.campaign);
    if (parsed.copy) {
      setCopy((prev) => ({
        eyebrow: parsed.copy?.eyebrow ?? prev.eyebrow,
        headline: parsed.copy?.headline ?? prev.headline,
        subhead: parsed.copy?.subhead ?? prev.subhead,
        cta: parsed.copy?.cta ?? prev.cta,
        cta_href: parsed.copy?.cta_href ?? prev.cta_href,
        legal: parsed.copy?.legal ?? null,
        brief: prev.brief,
      }));
    }
    if (parsed.canvases && parsed.canvases.length > 0) {
      setSelectedCanvases(new Set(parsed.canvases.map((c) => c.name)));
    }
  }

  async function onUploadRequestFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;

    setError(null);
    setUploadNotice(null);
    try {
      const parsed = JSON.parse(await file.text()) as NewRequestFile;
      applyRequestFile(parsed);
      setUploadNotice(`Loaded '${file.name}' — jump straight to Review, or adjust the details first.`);
      setStep(4);
    } catch (err) {
      setError(`Couldn't parse ${file.name}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  function loadShortcut(r: PastRequest) {
    setCampaign(r.campaign ?? "");
    setCopy({ ...EMPTY_COPY, ...r.copy });
    setSelectedCanvases(new Set(r.canvases.map((c) => c.name)));
    setUploadNotice(`Loaded the setup from '${r.campaign ?? "a past request"}'.`);
    setStep(4);
  }

  async function submit() {
    setError(null);
    const canvases = CANVAS_OPTIONS.filter((c) => selectedCanvases.has(c.name));
    if (!tenantId || !campaign || canvases.length === 0) {
      setError("A brand, a campaign name, and at least one canvas are required.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch("/api/requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenantId,
          campaign,
          copy: { ...copy, legal: copy.legal?.trim() ? copy.legal : null },
          canvases,
          inspirations: [],
        }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error ?? "submission failed");
      router.push(`/requests/${json.request_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const shortcuts = showAllShortcuts ? pastRequests : pastRequests.slice(0, 4);

  return (
    <div className="page composer-shell">
      <div className="stepper">
        {STEPS.map((label, i) => {
          const n = i + 1;
          const state = n === step ? "active" : n < step ? "done" : "";
          return (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <div className={`step ${state}`}>
                <span className="step-index">{n}</span>
                {label}
              </div>
              {n < STEPS.length && <span className="sep" />}
            </div>
          );
        })}
      </div>

      {step === 1 && (
        <>
          <div className="composer-heading">
            <h1>What do you want to build?</h1>
            <p>Describe it, or pick a play below. Your agent pulls from the Brain and stays inside the guardrails.</p>
          </div>

          <div className="composer-box">
            <div className="chip-row">
              <span className="chip select-chip">
                <Sparkles size={14} />
                <select value={tenantId} onChange={(e) => setTenantId(e.target.value)}>
                  {tenants.length === 0 && <option>No brands onboarded</option>}
                  {tenants.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </span>
              <span className="chip">
                <Palette size={14} />
                {activeTenant?.brand_kit_bucket ?? "no brand kit"}
              </span>
              <span className="chip">
                <BookOpen size={14} />
                DESIGN.md
              </span>
              <span className="chip">
                <LayoutGrid size={14} />
                {CANVAS_OPTIONS.length} canvas templates
              </span>
              <span className="chip">
                <History size={14} />
                {pastRequests.length} past request{pastRequests.length === 1 ? "" : "s"}
              </span>
            </div>

            <textarea
              className="composer-textarea"
              placeholder="Tell the agent what you want to create…"
              value={copy.brief ?? ""}
              onChange={(e) => setCopy((c) => ({ ...c, brief: e.target.value }))}
            />

            <div className="composer-footer">
              <button className="ghost" type="button" onClick={() => fileInputRef.current?.click()}>
                <Paperclip size={16} />
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="application/json"
                style={{ display: "none" }}
                onChange={onUploadRequestFile}
              />
              <div style={{ display: "flex", alignItems: "center", gap: "0.85rem" }}>
                <button className="skip-link" type="button" onClick={() => setStep(2)}>
                  Skip to inspiration
                </button>
                <button className="composer-submit" type="button" onClick={() => setStep(2)} disabled={!tenantId}>
                  <ArrowUp size={18} />
                </button>
              </div>
            </div>
          </div>

          {uploadNotice && (
            <p className="muted" style={{ textAlign: "center", marginTop: "0.75rem" }}>
              {uploadNotice}
            </p>
          )}
          {error && <p className="error" style={{ textAlign: "center" }}>{error}</p>}

          <div className="category-row">
            {CATEGORIES.map(({ label, icon: Icon }) => (
              <button
                key={label}
                type="button"
                className="category-chip"
                onClick={() =>
                  setCopy((c) => ({ ...c, brief: `${c.brief ? c.brief + " " : ""}[${label}] ` }))
                }
              >
                <Icon size={14} />
                {label}
              </button>
            ))}
          </div>

          <div className="shortcuts-header">
            <span>Agent shortcuts — one click loads a saved setup: task, canvases, brand kit</span>
            {pastRequests.length > 4 && (
              <button type="button" onClick={() => setShowAllShortcuts((v) => !v)}>
                {showAllShortcuts ? "Show less" : "Browse all"}
              </button>
            )}
          </div>
          {shortcuts.length > 0 ? (
            <div className="shortcut-grid">
              {shortcuts.map((r) => (
                <button key={r.id} type="button" className="shortcut-card" onClick={() => loadShortcut(r)}>
                  <div className="icon">
                    <Sparkles size={14} />
                  </div>
                  <div className="title">{r.campaign ?? "(untitled)"}</div>
                  <div className="meta">{r.canvases?.length ?? 0} sizes</div>
                </button>
              ))}
            </div>
          ) : (
            <p className="muted" style={{ textAlign: "center" }}>
              No past requests for this brand yet — nothing to reuse.
            </p>
          )}
        </>
      )}

      {step === 2 && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Choose inspiration</h2>
          <p className="muted">
            Optional. This build tracks selected inspiration filenames on the request, but
            hydration doesn&apos;t fetch them into the agent&apos;s sandbox yet (a known,
            flagged gap — see phase1.md) — so skipping is honest, not a shortcut.
          </p>
          <div className="wizard-actions">
            <button className="secondary" onClick={() => setStep(1)}>
              Back
            </button>
            <button onClick={() => setStep(3)}>Skip / Continue</button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Add details</h2>

          <div className="field">
            <label htmlFor="campaign">Campaign name</label>
            <input id="campaign" type="text" value={campaign} onChange={(e) => setCampaign(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="eyebrow">Eyebrow</label>
            <input
              id="eyebrow"
              type="text"
              value={copy.eyebrow}
              onChange={(e) => setCopy((c) => ({ ...c, eyebrow: e.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="headline">Headline</label>
            <input
              id="headline"
              type="text"
              value={copy.headline}
              onChange={(e) => setCopy((c) => ({ ...c, headline: e.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="subhead">Subhead</label>
            <textarea
              id="subhead"
              rows={2}
              value={copy.subhead}
              onChange={(e) => setCopy((c) => ({ ...c, subhead: e.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="cta">CTA label</label>
            <input
              id="cta"
              type="text"
              value={copy.cta}
              onChange={(e) => setCopy((c) => ({ ...c, cta: e.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="cta_href">CTA link</label>
            <input
              id="cta_href"
              type="url"
              value={copy.cta_href}
              onChange={(e) => setCopy((c) => ({ ...c, cta_href: e.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="legal">Legal / fine print (optional)</label>
            <input
              id="legal"
              type="text"
              value={copy.legal ?? ""}
              onChange={(e) => setCopy((c) => ({ ...c, legal: e.target.value }))}
            />
          </div>
          <div className="field">
            <label>Canvas sizes</label>
            <div className="checkbox-row">
              {CANVAS_OPTIONS.map((c) => (
                <label key={c.name}>
                  <input
                    type="checkbox"
                    checked={selectedCanvases.has(c.name)}
                    onChange={() => toggleCanvas(c.name)}
                  />
                  {c.name} ({c.width}×{c.height})
                </label>
              ))}
            </div>
          </div>

          <div className="wizard-actions">
            <button className="secondary" onClick={() => setStep(2)}>
              Back
            </button>
            <button onClick={() => setStep(4)}>Continue to review</button>
          </div>
        </div>
      )}

      {step === 4 && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Review & generate</h2>
          <dl className="review-grid">
            <dt>Brand</dt>
            <dd>{activeTenant?.name ?? "—"}</dd>
            <dt>Campaign</dt>
            <dd>{campaign || "—"}</dd>
            <dt>Eyebrow</dt>
            <dd>{copy.eyebrow || "—"}</dd>
            <dt>Headline</dt>
            <dd>{copy.headline || "—"}</dd>
            <dt>Subhead</dt>
            <dd>{copy.subhead || "—"}</dd>
            <dt>CTA</dt>
            <dd>
              {copy.cta || "—"} {copy.cta_href && `→ ${copy.cta_href}`}
            </dd>
            <dt>Canvases</dt>
            <dd>{Array.from(selectedCanvases).join(", ") || "—"}</dd>
          </dl>

          {error && <p className="error">{error}</p>}
          <p className="muted" style={{ fontSize: "0.82rem" }}>
            Generating queues a real run — picked up by the worker within seconds and executed
            in a real E2B sandbox. This spends real Anthropic + OpenAI budget.
          </p>

          <div className="wizard-actions">
            <button className="secondary" onClick={() => setStep(3)}>
              Back
            </button>
            <button onClick={submit} disabled={submitting}>
              {submitting ? "Submitting…" : "Generate ad"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
