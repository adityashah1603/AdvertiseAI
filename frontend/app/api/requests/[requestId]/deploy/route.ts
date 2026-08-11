import { NextRequest, NextResponse } from "next/server";
import { getServerSupabase } from "@/lib/supabase";
import type { RequestRow, Revision } from "@/lib/types";

// POST: fires a deploy run for the request's CURRENT latest revision - same
// "latest revision must be ready" precondition the edit route already
// checks (hydrate_deploy() refuses otherwise), but unlike edit, a deploy
// never produces a new revision - it publishes the existing one exactly as
// rendered. runs.revision_number here names WHICH existing revision to
// deploy, not one to be created, and no new `revisions` row is inserted.
//
// This handler never touches E2B/Anthropic/Adstream - it only writes one
// Postgres row. The already-running dispatcher (worker/orchestrator/
// dispatcher.py --serve) claims it via claim_next_deploy_run() and executes
// it in its own independent pool, same trust boundary as every other route
// here.
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ requestId: string }> }
) {
  const { requestId } = await params;

  const client = getServerSupabase();

  const { data: request, error: requestErr } = await client
    .from("requests")
    .select("*")
    .eq("id", requestId)
    .maybeSingle();
  if (requestErr) return NextResponse.json({ error: requestErr.message }, { status: 500 });
  if (!request) return NextResponse.json({ error: "request not found" }, { status: 404 });

  const { data: revisions, error: revisionsErr } = await client
    .from("revisions")
    .select("*")
    .eq("request_id", requestId)
    .order("revision_number", { ascending: false })
    .limit(1);
  if (revisionsErr) return NextResponse.json({ error: revisionsErr.message }, { status: 500 });

  const latest = (revisions?.[0] ?? null) as Revision | null;
  if (!latest || latest.status !== "ready") {
    return NextResponse.json(
      { error: "the latest revision isn't 'ready' yet - wait for it to finish before deploying" },
      { status: 409 }
    );
  }

  const { data: run, error: runErr } = await client
    .from("runs")
    .insert({
      type: "deploy",
      tenant_id: (request as RequestRow).tenant_id,
      request_id: requestId,
      revision_number: latest.revision_number,
      status: "queued",
      reason: "ui-deploy",
    })
    .select()
    .single();
  if (runErr || !run) {
    return NextResponse.json({ error: runErr?.message ?? "run insert failed" }, { status: 500 });
  }

  return NextResponse.json(
    { revision_number: latest.revision_number, run_id: run.id },
    { status: 201 }
  );
}
