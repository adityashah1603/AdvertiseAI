import { NextRequest, NextResponse } from "next/server";
import { getServerSupabase } from "@/lib/supabase";
import { onboardTenant, type UploadFile } from "@/lib/onboardTenant";
import type { Tenant } from "@/lib/types";

// GET: the live tenant list every picker in the UI reads from - never a
// hardcoded brand name anywhere in this file or its callers.
export async function GET() {
  const client = getServerSupabase();
  const { data, error } = await client
    .from("tenants")
    .select("id, slug, name, brand_kit_bucket, jobs_bucket, created_at")
    .order("name", { ascending: true });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ tenants: data as Tenant[] });
}

const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?$/;

// POST: the real "a brand-new company shows up" path. Accepts multipart
// form data - a slug, a display name, one DESIGN.md file, any number of
// font files, and any number of brand-asset files - and calls the exact
// same onboardTenant() a CLI script would, so there is exactly one
// onboarding implementation this endpoint exercises, not a parallel one.
export async function POST(req: NextRequest) {
  const form = await req.formData();

  const slug = String(form.get("slug") ?? "").trim().toLowerCase();
  const name = String(form.get("name") ?? "").trim();
  const designMd = form.get("designMd");
  const fontFiles = form.getAll("fonts");
  const brandFiles = form.getAll("brand");

  if (!SLUG_RE.test(slug)) {
    return NextResponse.json(
      { error: "slug must be lowercase letters/numbers/hyphens, e.g. 'patagonia'" },
      { status: 400 }
    );
  }
  if (!name) {
    return NextResponse.json({ error: "name is required" }, { status: 400 });
  }
  if (!(designMd instanceof File)) {
    return NextResponse.json({ error: "DESIGN.md file is required" }, { status: 400 });
  }

  const files: UploadFile[] = [];
  files.push({
    relPath: "DESIGN.md",
    data: new Uint8Array(await designMd.arrayBuffer()),
    contentType: "text/markdown",
  });
  for (const f of fontFiles) {
    if (f instanceof File) {
      files.push({
        relPath: `fonts/${f.name}`,
        data: new Uint8Array(await f.arrayBuffer()),
        contentType: f.type || undefined,
      });
    }
  }
  for (const f of brandFiles) {
    if (f instanceof File) {
      files.push({
        relPath: `brand/${f.name}`,
        data: new Uint8Array(await f.arrayBuffer()),
        contentType: f.type || undefined,
      });
    }
  }

  try {
    const client = getServerSupabase();
    const tenant = await onboardTenant(client, slug, name, files);
    return NextResponse.json({ tenant }, { status: 201 });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
