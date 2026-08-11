import { NextRequest, NextResponse } from "next/server";
import { getServerSupabase } from "@/lib/supabase";
import type { Inspiration } from "@/lib/types";

const SIGNED_URL_TTL_S = 120;

// GET: lists one tenant's inspiration images (filename + a short-TTL signed
// thumbnail URL each), read from that tenant's own inspirations_bucket -
// same signed-URL pattern already used for plate/render assets in
// app/api/requests/[requestId]/route.ts. Powers the composer's "Choose
// inspiration" step; a request only ever carries the exact filenames a user
// checks here (requests.inspirations), never the whole bucket - matching
// SKILL.md's "consult one only when the request attaches it by filename."
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ tenantId: string }> }
) {
  const { tenantId } = await params;
  const client = getServerSupabase();

  const { data: tenant, error: tenantErr } = await client
    .from("tenants")
    .select("inspirations_bucket")
    .eq("id", tenantId)
    .maybeSingle();
  if (tenantErr) return NextResponse.json({ error: tenantErr.message }, { status: 500 });
  if (!tenant) return NextResponse.json({ error: "unknown tenant_id" }, { status: 404 });
  if (!tenant.inspirations_bucket) {
    return NextResponse.json({ inspirations: [] as Inspiration[] });
  }

  const { data: entries, error: listErr } = await client.storage
    .from(tenant.inspirations_bucket)
    .list();
  if (listErr) return NextResponse.json({ error: listErr.message }, { status: 500 });

  const files = (entries ?? []).filter((e) => e.id !== null); // real files only, not folder markers
  const inspirations: Inspiration[] = await Promise.all(
    files.map(async (entry) => {
      const { data, error } = await client.storage
        .from(tenant.inspirations_bucket as string)
        .createSignedUrl(entry.name, SIGNED_URL_TTL_S);
      return { filename: entry.name, url: error || !data ? null : data.signedUrl };
    })
  );

  return NextResponse.json({ inspirations });
}
