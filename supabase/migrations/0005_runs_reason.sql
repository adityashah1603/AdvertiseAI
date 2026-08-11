-- Traceability for reruns: WHY a given run attempt exists (a fresh
-- generation, a retry after a transient failure, part of a deliberate
-- concurrency-test batch, an edit, etc.), set by whichever code path
-- enqueues the run (enqueue.py's enqueue_request(reason=...)) and carried
-- through to a small per-attempt log file at
-- revisions/{n}/attempts/{timestamp}-{run_id}-{reason}.json (see
-- execute_run.py) - so a human looking at Storage can see not just what a
-- revision's current output is, but the history of attempts that produced
-- it, without needing to cross-reference the runs table.
alter table runs add column reason text not null default 'initial';
