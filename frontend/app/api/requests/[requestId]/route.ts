import { NextRequest, NextResponse } from "next/server";
import { getServerSupabase } from "@/lib/supabase";
import type { Asset, Comment, Deploy, RequestRow, Revision, Run } from "@/lib/types";

const SIGNED_URL_TTL_S = 120;

// GET: read-only status/results for one request - polled by the frontend
// (requests/[requestId]/page.tsx) every ~2s while a run is in flight. Reads
// only Postgres + Storage, exactly like execute_run.py's own success
// verification does - never reaches into a sandbox (there usually isn't
// one alive by the time this is called anyway).
export async function GET(
  _req: NextRequest,
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

  const { data: tenantRow } = await client
    .from("tenants")
    .select("name, slug, jobs_bucket")
    .eq("id", (request as RequestRow).tenant_id)
    .maybeSingle();

  const { data: revisions, error: revisionsErr } = await client
    .from("revisions")
    .select("*")
    .eq("request_id", requestId)
    .order("revision_number", { ascending: false });
  if (revisionsErr) return NextResponse.json({ error: revisionsErr.message }, { status: 500 });

  const latest = (revisions?.[0] ?? null) as Revision | null;

  let run: Run | null = null;
  let assets: (Asset & { plate_url: string | null; render_url: string | null })[] = [];

  if (latest) {
    // Scoped to type != 'deploy' on purpose - a deploy run shares the same
    // revision_number as the revision it deploys (it never produces a new
    // one), so without this filter a deploy fired against the latest
    // revision would outrank the actual generate/edit run here by
    // created_at and silently swap what this field means. Deploy state has
    // its own field below instead.
    const { data: runs, error: runErr } = await client
      .from("runs")
      .select("*")
      .eq("request_id", requestId)
      .eq("revision_number", latest.revision_number)
      .neq("type", "deploy")
      .order("created_at", { ascending: false })
      .limit(1);
    if (runErr) return NextResponse.json({ error: runErr.message }, { status: 500 });
    run = (runs?.[0] ?? null) as Run | null;

    const { data: assetRows, error: assetsErr } = await client
      .from("assets")
      .select("*")
      .eq("revision_id", latest.id);
    if (assetsErr) return NextResponse.json({ error: assetsErr.message }, { status: 500 });

    if (assetRows && assetRows.length > 0 && tenantRow?.jobs_bucket) {
      const jobsBucket = tenantRow.jobs_bucket;
      assets = await Promise.all(
        (assetRows as Asset[]).map(async (asset) => {
          const [plateUrl, renderUrl] = await Promise.all([
            asset.plate_path ? signOrNull(client, jobsBucket, asset.plate_path) : null,
            asset.png_path ? signOrNull(client, jobsBucket, asset.png_path) : null,
          ]);
          return { ...asset, plate_url: plateUrl, render_url: renderUrl };
        })
      );
    }
  }

  // Most recent deploy attempt for this request, regardless of which
  // revision it targeted - deploying an older revision while a newer one
  // exists is a valid (if unusual) action, so this deliberately isn't
  // scoped to `latest` the way `run`/`assets` above are. A deployRun with
  // no matching `deploys` row yet means still queued/running - a real
  // `deploys` row (recording_path, verified) only ever exists once
  // execute_deploy_run.py's own Storage-verified check passed.
  const { data: deployRuns } = await client
    .from("runs")
    .select("*")
    .eq("request_id", requestId)
    .eq("type", "deploy")
    .order("created_at", { ascending: false })
    .limit(1);
  const deployRun = (deployRuns?.[0] ?? null) as Run | null;

  let deploy: (Deploy & { recording_url: string | null }) | null = null;
  if (deployRun) {
    const { data: deployRows } = await client
      .from("deploys")
      .select("*")
      .eq("run_id", deployRun.id)
      .maybeSingle();
    if (deployRows && tenantRow?.jobs_bucket) {
      const recordingUrl = deployRows.recording_path
        ? await signOrNull(client, tenantRow.jobs_bucket, deployRows.recording_path)
        : null;
      deploy = { ...(deployRows as Deploy), recording_url: recordingUrl };
    }
  }

  // All comments across every revision of this request - the frontend's
  // "hide older revision comments" toggle (DECISIONS.md §3.2) filters
  // client-side by revision_number, so this endpoint just hands back
  // everything with revision_number attached rather than deciding for it.
  const revisionNumberById = new Map((revisions ?? []).map((r) => [r.id, r.revision_number]));
  const { data: commentRows, error: commentsErr } = await client
    .from("comments")
    .select("*")
    .eq("request_id", requestId)
    .order("created_at", { ascending: false });
  if (commentsErr) return NextResponse.json({ error: commentsErr.message }, { status: 500 });
  const comments = (commentRows ?? []).map((c) => ({
    ...(c as Comment),
    revision_number: revisionNumberById.get(c.revision_id) ?? null,
  }));

  return NextResponse.json({
    request: request as RequestRow,
    tenant: tenantRow ? { name: tenantRow.name, slug: tenantRow.slug } : null,
    revisions: (revisions ?? []) as Revision[],
    revision: latest,
    run,
    assets,
    comments,
    deployRun,
    deploy,
  });
}

async function signOrNull(
  client: ReturnType<typeof getServerSupabase>,
  bucket: string,
  path: string
): Promise<string | null> {
  const { data, error } = await client.storage
    .from(bucket)
    .createSignedUrl(path, SIGNED_URL_TTL_S);
  if (error || !data) return null; // not uploaded yet (run still in progress) - not an error to surface
  return data.signedUrl;
}
