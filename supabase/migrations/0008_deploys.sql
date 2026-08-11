-- Phase 4: deployment. One row per deploy attempt, mirroring runs/assets'
-- shape - revision_id links back to the exact revision deployed, run_id to
-- the runs row (type='deploy', already a valid value per 0001_init.sql's
-- check constraint) that produced it.
--
-- verified is the load-bearing column: per the brief, "the run isn't over
-- until the detail page has been read and the result saved" - this column
-- is only ever set true by execute_deploy_run.py after reading the agent's
-- own RESULT.json, which itself only claims verified=true after a real
-- detail-page read-back inside the sandbox. Never set speculatively.
--
-- recording_path is a Storage path to a Playwright-recorded .webm (not
-- .mp4 - Playwright's own record_video_dir has no built-in mp4 export, and
-- a browser <video> tag plays webm natively, so no conversion step/ffmpeg
-- dependency was added). "No recording, no deploy": a deploy row is only
-- ever written on success, and execute_deploy_run.py treats a missing
-- recording in Storage as an automatic failure regardless of what
-- RESULT.json claims.
create table deploys (
  id uuid primary key default gen_random_uuid(),
  revision_id uuid not null references revisions(id),
  run_id uuid not null references runs(id),
  adstream_ad_name text,
  adstream_url text,
  verified boolean not null default false,
  recording_path text,
  status text not null check (status in ('pending', 'running', 'succeeded', 'failed')) default 'pending',
  created_at timestamptz not null default now()
);

create index deploys_revision_id_idx on deploys(revision_id);
