-- Phase 2: the concurrency cap mechanism required by ROADMAP.md section 5
-- ("a simple counter of runs.status='running', enforced before claiming a
-- new queued run - a Postgres row lock / SELECT ... FOR UPDATE on a single
-- counter row is enough. No custom scheduler - a capped FIFO queue.").
--
-- Nothing before this migration actually enforced a cap: run_generation.py
-- inserted a run and executed it immediately, one call at a time. This adds
-- the real claim path multiple dispatcher workers can call concurrently
-- without racing past the cap.

-- dispatch_lock exists purely as something to hold a row lock on - it is
-- NOT where the running count lives (that's always counted fresh from
-- runs.status, so it can never drift out of sync with reality). Locking
-- this one sentinel row serializes every concurrent claim_next_run() call
-- into a single queue, which is what actually prevents two workers from
-- both reading "1 running, cap is 2" at the same instant and both
-- claiming a second run.
create table dispatch_lock (
  id int primary key,
  locked_at timestamptz
);
insert into dispatch_lock (id, locked_at) values (1, now());

-- Atomically claims the oldest queued run, but only if fewer than p_cap
-- runs are currently 'running'. Returns zero rows if the cap is full or
-- the queue is empty - callers poll again later. FOR UPDATE SKIP LOCKED on
-- the runs row (on top of the dispatch_lock serialization above) means a
-- run some other transaction is mid-claim on is simply skipped rather than
-- blocked on, though in practice dispatch_lock alone already serializes
-- every caller.
create or replace function claim_next_run(p_cap integer)
returns setof runs
language plpgsql
as $$
declare
  v_running_count integer;
  v_claimed_id uuid;
begin
  perform 1 from dispatch_lock where id = 1 for update;

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
