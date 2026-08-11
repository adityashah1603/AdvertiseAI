// Mirrors supabase/migrations/0001_init.sql + 0004_comments.sql +
// 0007_inspirations_bucket.sql exactly - this file has no independent
// opinion about the schema, it just names it for the TypeScript side.

export type Tenant = {
  id: string;
  slug: string;
  name: string;
  brand_kit_bucket: string | null;
  jobs_bucket: string | null;
  inspirations_bucket: string | null;
  created_at: string;
};

export type Inspiration = { filename: string; url: string | null };

export type Canvas = { name: string; width: number; height: number };

export type Copy = {
  eyebrow: string;
  headline: string;
  subhead: string;
  cta: string;
  cta_href: string;
  legal: string | null;
  // Free-text creative brief from the composer's "what do you want to
  // build" step - context for a human reviewing the request, stored
  // alongside the literal on-canvas copy fields above. Not yet threaded
  // into agent_runner.py's prompt (same "known, flagged gap" posture as
  // inspirations not being fetched) - the agent only ever sees the exact
  // eyebrow/headline/subhead/cta text, never this.
  brief?: string | null;
};

export type RequestRow = {
  id: string;
  tenant_id: string;
  kind: "new" | "edit";
  campaign: string | null;
  copy: Copy;
  canvases: Canvas[];
  inspirations: string[];
  parent_request_id: string | null;
  created_by: string | null;
  created_at: string;
};

export type RevisionStatus = "pending" | "generating" | "ready" | "failed";

export type Revision = {
  id: string;
  request_id: string;
  revision_number: number;
  status: RevisionStatus;
  run_id: string | null;
  created_at: string;
};

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "crashed";

export type Run = {
  id: string;
  type: "generate" | "edit" | "deploy";
  tenant_id: string;
  request_id: string;
  revision_id: string | null;
  revision_number: number | null;
  status: RunStatus;
  sandbox_id: string | null;
  error_message: string | null;
  transcript_path: string | null;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  reason: string | null;
};

export type Asset = {
  id: string;
  revision_id: string;
  canvas_name: string;
  width: number;
  height: number;
  plate_path: string | null;
  html_path: string | null;
  png_path: string | null;
  created_at: string;
};

export type CommentStatus = "open" | "resolved" | "stale" | "orphaned";

export type Region = { x: number; y: number; width: number; height: number };

export type Comment = {
  id: string;
  request_id: string;
  revision_id: string;
  canvas_name: string;
  region: Region;
  body: string;
  author: string | null;
  status: CommentStatus;
  created_at: string;
};

// The one place canvas options are defined - a global-tier decision (same
// menu for every tenant), never a per-brand list. Matches
// worker/hydration/create_test_request.py's CANVASES.
export const CANVAS_OPTIONS: Canvas[] = [
  { name: "square", width: 1080, height: 1080 },
  { name: "landscape", width: 1200, height: 628 },
  { name: "portrait", width: 1080, height: 1350 },
  { name: "story", width: 1080, height: 1920 },
];
