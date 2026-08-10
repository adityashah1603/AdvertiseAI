-- Phase 1 minimal schema. Deliberately excludes comments/deploys tables -
-- those arrive with the feedback surface (Step 6) and deployment (Step 7)
-- phases, per ROADMAP.md's storage layout and an explicit decision to keep
-- this milestone to only what proves the hydrate/generate/save loop works.

create extension if not exists "pgcrypto";

-- One row per customer (Kahua, Emplifi, and whatever brand shows up on day
-- two). Nothing anywhere else in this schema may reference a tenant by
-- name - only by this id. That's what makes "no tenant-specific handling
-- anywhere in code" checkable: if a query needs to know it's Kahua, it's
-- wrong.
--
-- brand_kit_bucket / jobs_bucket: each tenant gets its own two Storage
-- buckets (created at onboarding time by onboard_tenant(), never by hand),
-- rather than a shared bucket with a tenant_id-prefixed path. Recorded
-- explicitly here rather than re-derived from the id everywhere a caller
-- needs it, so the naming convention can change later without touching
-- every reader.
create table tenants (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  name text not null,
  brand_kit_bucket text unique,
  jobs_bucket text unique,
  created_at timestamptz not null default now()
);

-- A "task" - one operator-submitted job. copy/canvases are jsonb rather
-- than fixed columns because the copy fields (eyebrow/headline/subhead/cta)
-- are a brief-defined shape we don't want to hard-migrate every time it
-- changes, and canvases is a variable-length list of {name,width,height}.
create table requests (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  kind text not null check (kind in ('new', 'edit')),
  campaign text,
  copy jsonb not null,
  canvases jsonb not null,
  inspirations text[] not null default '{}',
  parent_request_id uuid references requests(id),
  created_by text,
  created_at timestamptz not null default now()
);

-- Every successful generation or edit produces a NEW revision row - nothing
-- is ever overwritten in place. That's what makes "get back to revision 3
-- after revision 4 failed" a read, not a recovery operation.
create table revisions (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null references requests(id),
  revision_number int not null,
  status text not null check (status in ('pending', 'generating', 'ready', 'failed')) default 'pending',
  run_id uuid,
  created_at timestamptz not null default now(),
  unique (request_id, revision_number)
);

-- One row per canvas size within a revision. The *_path columns are
-- Supabase Storage paths (jobs/{request_id}/revisions/{n}/...), not the
-- files themselves - the files are the durable artifact, these rows are
-- the index into them.
create table assets (
  id uuid primary key default gen_random_uuid(),
  revision_id uuid not null references revisions(id),
  canvas_name text not null,
  width int not null,
  height int not null,
  plate_path text,
  html_path text,
  png_path text,
  created_at timestamptz not null default now(),
  unique (revision_id, canvas_name)
);

-- One row per sandbox run, generate/edit/deploy alike. This is the audit
-- trail: sandbox_id is the E2B-issued opaque id (never a human-readable
-- tenant/task name - that's a disqualifier), transcript_path points at the
-- full raw agent transcript saved to Storage regardless of success/failure.
create table runs (
  id uuid primary key default gen_random_uuid(),
  type text not null check (type in ('generate', 'edit', 'deploy')),
  tenant_id uuid not null references tenants(id),
  request_id uuid not null references requests(id),
  revision_id uuid references revisions(id),
  status text not null check (status in ('queued', 'running', 'succeeded', 'failed', 'crashed')) default 'queued',
  sandbox_id text,
  error_message text,
  transcript_path text,
  started_at timestamptz,
  ended_at timestamptz,
  created_at timestamptz not null default now()
);

-- Added after both tables exist - revisions.run_id and runs.revision_id
-- point at each other (a revision knows which run produced it; a run
-- knows which revision it produced), so one side has to be a deferred FK.
alter table revisions
  add constraint revisions_run_id_fkey foreign key (run_id) references runs(id);

create index requests_tenant_id_idx on requests(tenant_id);
create index revisions_request_id_idx on revisions(request_id);
create index assets_revision_id_idx on assets(revision_id);
create index runs_tenant_id_idx on runs(tenant_id);
create index runs_status_idx on runs(status);
