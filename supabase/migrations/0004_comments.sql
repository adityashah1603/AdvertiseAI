-- Phase 2/3 boundary: the minimum needed for a backend-only edit flow
-- (ROADMAP.md section 4.1's edit path: "the prior revision's assets plus
-- any open comments with their region coordinates"), pulled forward ahead
-- of the full Phase 3 feedback-surface frontend because Phase 2's own
-- "horrifying test case" and third-brand checklist items need a real edit
-- to exist, not just a new request.
--
-- revision_id is "the revision the comment was left on" - i.e. the OLD
-- revision being viewed/critiqued, not the new one an edit run produces.
-- region is nullable-shaped-but-required jsonb {x,y,width,height} - an
-- area, not a point, per ROADMAP.md's explicit choice ("pinned comments
-- (area, not point)").
create table comments (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null references requests(id),
  revision_id uuid not null references revisions(id),
  canvas_name text not null,
  region jsonb not null,
  body text not null,
  author text,
  status text not null check (status in ('open', 'resolved', 'stale', 'orphaned')) default 'open',
  created_at timestamptz not null default now()
);

create index comments_request_id_idx on comments(request_id);
create index comments_revision_id_idx on comments(revision_id);
create index comments_status_idx on comments(status);
