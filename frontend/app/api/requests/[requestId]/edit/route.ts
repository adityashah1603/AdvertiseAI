import { NextRequest, NextResponse } from "next/server";
import { getServerSupabase } from "@/lib/supabase";
import type { RequestRow, Region, Revision } from "@/lib/types";

type EditCommentInput = {
  canvas_name: string;
  region: Region;
  body: string;
  author?: string;
};

// POST: the minimal edit/feedback path (ROADMAP.md §4.1's edit shape,
// DECISIONS.md §3.2's comment lifecycle) - pins one or more comments to the
// CURRENT latest revision, then opens the NEXT revision as a queued 'edit'
// run. worker/hydration/generation.py's _hydrate_edit_context() derives
// "is this an edit" purely from revision_number > 1 and a succeeded prior
// run existing - it refuses to hydrate otherwise, so this route checks the
// same precondition up front for a clear error instead of a run that fails
// loudly three steps later inside the sandbox.
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ requestId: string }> }
) {
  const { requestId } = await params;
  const body = await req.json().catch(() => null);
  const comments = (body?.comments ?? []) as EditCommentInput[];

  if (!Array.isArray(comments) || comments.length === 0) {
    return NextResponse.json({ error: "at least one comment is required" }, { status: 400 });
  }
  for (const c of comments) {
    if (!c.canvas_name || !c.body || !c.region) {
      return NextResponse.json(
        { error: "each comment needs canvas_name, region {x,y,width,height}, and body" },
        { status: 400 }
      );
    }
  }

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
      { error: "the latest revision isn't 'ready' yet - wait for it to finish before commenting" },
      { status: 409 }
    );
  }

  const { error: commentsErr } = await client.from("comments").insert(
    comments.map((c) => ({
      request_id: requestId,
      revision_id: latest.id,
      canvas_name: c.canvas_name,
      region: c.region,
      body: c.body,
      author: c.author ?? "ui",
    }))
  );
  if (commentsErr) return NextResponse.json({ error: commentsErr.message }, { status: 500 });

  const nextRevisionNumber = latest.revision_number + 1;
  const { error: nextRevisionErr } = await client.from("revisions").insert({
    request_id: requestId,
    revision_number: nextRevisionNumber,
    status: "pending",
  });
  if (nextRevisionErr) return NextResponse.json({ error: nextRevisionErr.message }, { status: 500 });

  const { data: run, error: runErr } = await client
    .from("runs")
    .insert({
      type: "edit",
      tenant_id: (request as RequestRow).tenant_id,
      request_id: requestId,
      revision_number: nextRevisionNumber,
      status: "queued",
      reason: "ui-edit",
    })
    .select()
    .single();
  if (runErr || !run) {
    return NextResponse.json({ error: runErr?.message ?? "run insert failed" }, { status: 500 });
  }

  return NextResponse.json(
    { revision_number: nextRevisionNumber, run_id: run.id },
    { status: 201 }
  );
}
