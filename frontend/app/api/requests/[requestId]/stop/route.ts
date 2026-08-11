import { NextRequest, NextResponse } from "next/server";
import { getServerSupabase } from "@/lib/supabase";

// POST: requests that an in-flight run be stopped. Same trust boundary as
// every other route here - this ONLY writes a Postgres flag
// (runs.cancel_requested); it never touches E2B directly. The orchestrator
// (which already polls the live sandbox every ~15s for metrics while
// waiting on the agent) checks this same flag on the same cadence and
// performs the actual kill itself, using the same path already proven live
// by this session's own deliberate crash-recovery tests.
//
// Takes an explicit run_id rather than inferring "whichever run is
// running" - a request can have a generate/edit run and a deploy run both
// in flight at once (independent concurrency pools), so there is no single
// implicit answer to "the" running run.
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ requestId: string }> }
) {
  const { requestId } = await params;
  const body = await req.json().catch(() => null);
  const runId = body?.run_id as string | undefined;
  if (!runId) {
    return NextResponse.json({ error: "run_id is required" }, { status: 400 });
  }

  const client = getServerSupabase();

  const { data: run, error: runErr } = await client
    .from("runs")
    .select("id, request_id, status")
    .eq("id", runId)
    .maybeSingle();
  if (runErr) return NextResponse.json({ error: runErr.message }, { status: 500 });
  if (!run || run.request_id !== requestId) {
    return NextResponse.json({ error: "run not found on this request" }, { status: 404 });
  }
  if (run.status !== "running") {
    return NextResponse.json(
      { error: `run is '${run.status}', not 'running' - nothing to stop` },
      { status: 409 }
    );
  }

  const { error: updateErr } = await client
    .from("runs")
    .update({ cancel_requested: true })
    .eq("id", runId);
  if (updateErr) return NextResponse.json({ error: updateErr.message }, { status: 500 });

  return NextResponse.json({ ok: true, run_id: runId }, { status: 202 });
}
