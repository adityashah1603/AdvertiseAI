import { NextRequest, NextResponse } from "next/server";
import { getServerSupabase } from "@/lib/supabase";
import type { Canvas, Copy } from "@/lib/types";

// GET: recent requests for one tenant - powers both the "Past work" count
// chip and the "Agent shortcuts" row (click a past request to reuse its
// whole payload) on the composer. Read-only, same trust boundary as every
// other Route Handler here.
export async function GET(req: NextRequest) {
  const tenantId = req.nextUrl.searchParams.get("tenant_id");
  if (!tenantId) {
    return NextResponse.json({ error: "tenant_id query param is required" }, { status: 400 });
  }
  const limit = Number(req.nextUrl.searchParams.get("limit") ?? "8");

  const client = getServerSupabase();
  const { data, error } = await client
    .from("requests")
    .select("id, campaign, copy, canvases, created_at")
    .eq("tenant_id", tenantId)
    .order("created_at", { ascending: false })
    .limit(limit);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ requests: data ?? [] });
}

// POST: everything a submission needs to start moving through the real
// pipeline - insert a requests row, its first (revision_number=1) revisions
// row, and a queued runs row. Row shapes here match
// worker/hydration/create_test_request.py + worker/orchestrator/enqueue.py
// exactly (same columns, same 'pending'/'queued' initial statuses) so the
// already-running Python dispatcher (worker/orchestrator/dispatcher.py
// --serve) doesn't care which side of the language boundary inserted the
// row - it just claims the next queued one via claim_next_run(), unchanged.
//
// This handler never touches E2B/Anthropic/OpenAI - it only writes three
// Postgres rows. Actually running the agent happens in a separate,
// already-running process (the dispatcher), never inside this request.
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body) {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const { tenant_id, campaign, copy, canvases, inspirations } = body as {
    tenant_id?: string;
    campaign?: string;
    copy?: Copy;
    canvases?: Canvas[];
    inspirations?: string[];
  };

  if (!tenant_id || !campaign || !copy || !canvases || canvases.length === 0) {
    return NextResponse.json(
      { error: "tenant_id, campaign, copy, and at least one canvas are required" },
      { status: 400 }
    );
  }

  const client = getServerSupabase();

  const { data: tenant, error: tenantErr } = await client
    .from("tenants")
    .select("id")
    .eq("id", tenant_id)
    .maybeSingle();
  if (tenantErr) {
    return NextResponse.json({ error: tenantErr.message }, { status: 500 });
  }
  if (!tenant) {
    return NextResponse.json({ error: `unknown tenant_id '${tenant_id}'` }, { status: 404 });
  }

  const { data: request, error: requestErr } = await client
    .from("requests")
    .insert({
      tenant_id,
      kind: "new",
      campaign,
      copy,
      canvases,
      inspirations: inspirations ?? [],
      created_by: "ui",
    })
    .select()
    .single();
  if (requestErr || !request) {
    return NextResponse.json({ error: requestErr?.message ?? "request insert failed" }, { status: 500 });
  }

  const { error: revisionErr } = await client.from("revisions").insert({
    request_id: request.id,
    revision_number: 1,
    status: "pending",
  });
  if (revisionErr) {
    return NextResponse.json({ error: revisionErr.message }, { status: 500 });
  }

  const { data: run, error: runErr } = await client
    .from("runs")
    .insert({
      type: "generate",
      tenant_id,
      request_id: request.id,
      revision_number: 1,
      status: "queued",
      reason: "ui-submission",
    })
    .select()
    .single();
  if (runErr || !run) {
    return NextResponse.json({ error: runErr?.message ?? "run insert failed" }, { status: 500 });
  }

  return NextResponse.json(
    { request_id: request.id, revision_number: 1, run_id: run.id },
    { status: 201 }
  );
}
