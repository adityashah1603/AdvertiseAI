"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

export default function OnboardPage() {
  const router = useRouter();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    const form = e.currentTarget;
    const formData = new FormData(form);

    if (!(formData.get("designMd") as File)?.name) {
      setError("A DESIGN.md file is required.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch("/api/tenants", { method: "POST", body: formData });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error ?? "onboarding failed");
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page narrow">
      <h1>Onboard a brand</h1>
      <p className="subtitle">
        Nothing here is brand-specific — this form calls the exact same onboarding path
        (<code>onboardTenant()</code>) for any company, live. No code changes, ever.
      </p>

      <form className="card" onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="slug">Slug (lowercase, hyphens only — used for storage bucket names)</label>
          <input
            id="slug"
            name="slug"
            type="text"
            placeholder="patagonia"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            pattern="[a-z0-9][a-z0-9-]*"
            required
          />
        </div>

        <div className="field">
          <label htmlFor="name">Display name</label>
          <input
            id="name"
            name="name"
            type="text"
            placeholder="Patagonia"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>

        <div className="field">
          <label htmlFor="designMd">DESIGN.md (the brand — palette, type, voice, rules)</label>
          <input id="designMd" name="designMd" type="file" accept=".md,text/markdown" required />
        </div>

        <div className="field">
          <label htmlFor="fonts">Font files (.ttf/.otf, any number)</label>
          <input id="fonts" name="fonts" type="file" multiple />
        </div>

        <div className="field">
          <label htmlFor="brand">
            Brand assets — logos, asset_manifest.json, tokens.json (any number)
          </label>
          <input id="brand" name="brand" type="file" multiple />
        </div>

        <div className="field">
          <label htmlFor="inspirations">
            Inspiration images — reference designs from this brand&apos;s own library, optional
            (any number). Treatment reference only, per SKILL.md — never a source of color, type,
            spacing, or copy.
          </label>
          <input id="inspirations" name="inspirations" type="file" multiple accept="image/*" />
        </div>

        {error && <p className="error">{error}</p>}

        <button type="submit" disabled={submitting}>
          {submitting ? "Onboarding…" : "Onboard brand"}
        </button>
      </form>
    </div>
  );
}
