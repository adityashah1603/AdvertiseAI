-- Phase 3 backlog item (DECISIONS.md SS6): a sandbox killed OUTSIDE
-- execute_run.py's own exception handling (a manual kill, a host crash, the
-- process itself dying) leaves a `running` row that never flips to
-- `failed`. claim_next_run() counts `running` rows against the cap, so one
-- orphaned row silently eats a concurrency slot forever - observed for real
-- once already, corrected by hand at the time.
--
-- Fix: claim_next_run() now self-heals before it does anything else -
-- expire any run that's been `running` well past its own sandbox timeout
-- (execute_run.py's SANDBOX_TIMEOUT_S = 900s / 15min; 20 minutes here is a
-- deliberate margin above that, not the same number, so a genuinely slow
-- but alive run is never mistaken for a dead one) and mark its matching
-- revision `failed` too - exactly what execute_run.py's own except block
-- would have written had the process not died uncleanly. This makes a
-- caller of claim_next_run() self-healing on every call, with no separate
-- sweep process to run or forget to run.
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
      and started_at < now() - interval '20 minutes'
    returning id, request_id, revision_number
  loop
    update revisions
    set status = 'failed'
    where request_id = v_expired.request_id
      and revision_number = v_expired.revision_number
      and status = 'generating';
  end loop;

  select count(*) into v_running_count from runs where status = 'running';
  if v_running_count >= p_cap then
    return;
  end if;

  select id into v_claimed_id
  from runs
  where status = 'queued'
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
