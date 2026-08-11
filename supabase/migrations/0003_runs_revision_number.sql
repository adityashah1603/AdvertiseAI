-- Phase 2: enqueueing and executing a run are now two separate steps
-- (enqueue.py inserts 'queued'; dispatcher.py's claim_next_run() flips it
-- to 'running' from a different process/thread, possibly much later).
-- Whatever claims a run needs to know which revision to hydrate without
-- re-deriving it - it can't assume "the newest pending revision for this
-- request" is unambiguous once edits exist (a request can have several
-- revisions). So the run row records its target revision_number directly,
-- at enqueue time, same as tenant_id/request_id.
alter table runs add column revision_number int;
