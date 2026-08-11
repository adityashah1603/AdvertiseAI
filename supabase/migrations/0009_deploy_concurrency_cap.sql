-- Phase 4: "two independent caps, not one - generation sandboxes and
-- deployment sandboxes contend for different resources (image-model rate
-- limits vs. browser sessions) and should never block each other"
-- (DECISIONS.md SS3.3 / ROADMAP.md SS3.1's locked decision). Until now
-- claim_next_run() counted/claimed across ALL run types together, which
-- was correct behavior for 'generate'/'edit' (they've always intentionally
-- shared one pool) but would have wrongly folded 'deploy' runs into that
-- same pool the moment they started existing.
--
-- claim_next_run() is scoped to exclude 'deploy' - safe to do
-- retroactively with zero behavior change for every run that has ever
-- actually existed, since no 'deploy' row existed anywhere before this
-- migration. A twin function, claim_next_deploy_run(), gets its own
-- independent cap and its own dispatch_lock-style serialization via a
-- second sentinel row, so a deploy claim and a generation claim can never
-- race each other's lock unnecessarily.
create table deploy_dispatch_lock (
  id int primary key,
  locked_at timestamptz
);
insert into deploy_dispatch_lock (id, locked_at) values (1, now());

create or replace function claim_next_run(p_cap integer)
returns setof runs
language plpgsql
as $$
declare
  v_running_count integer;
  v_claimed_id uuid;
  v_expired record;
begin
  perform 1 from dispatch_lock where id = 1 for update;

  for v_expired in
    update runs
    set status = 'failed',
        error_message = 'expired: no update within 20 minutes of claim, sandbox presumed dead',
        ended_at = now()
    where status = 'running'
      and type != 'deploy'
      and started_at < now() - interval '20 minutes'
    returning id, request_id, revision_number
  loop
    update revisions
    set status = 'failed'
    where request_id = v_expired.request_id
      and revision_number = v_expired.revision_number
      and status = 'generating';
  end loop;

  select count(*) into v_running_count from runs where status = 'running' and type != 'deploy';
  if v_running_count >= p_cap then
    return;
  end if;

  select id into v_claimed_id
  from runs
  where status = 'queued' and type != 'deploy'
  order by created_at asc
  limit 1
  for update skip locked;

  if v_claimed_id is null then
    return;
  end if;

  update runs
  set status = 'running', started_at = now()
  where id = v_claimed_id;

  return query select * from runs where id = v_claimed_id;
end;
$$;

-- Deploy runs get the same stale-row self-healing as claim_next_run() -
-- a sandbox killed outside execute_deploy_run.py's own exception handling
-- shouldn't be able to eat a deployment slot forever either.
create or replace function claim_next_deploy_run(p_cap integer)
returns setof runs
language plpgsql
as $$
declare
  v_running_count integer;
  v_claimed_id uuid;
begin
  perform 1 from deploy_dispatch_lock where id = 1 for update;

  update runs
  set status = 'failed',
      error_message = 'expired: no update within 20 minutes of claim, sandbox presumed dead'
  where status = 'running'
    and type = 'deploy'
    and started_at < now() - interval '20 minutes';

  select count(*) into v_running_count from runs where status = 'running' and type = 'deploy';
  if v_running_count >= p_cap then
    return;
  end if;

  select id into v_claimed_id
  from runs
  where status = 'queued' and type = 'deploy'
  order by created_at asc
  limit 1
  for update skip locked;

  if v_claimed_id is null then
    return;
  end if;

  update runs
  set status = 'running', started_at = now()
  where id = v_claimed_id;

  return query select * from runs where id = v_claimed_id;
end;
$$;
