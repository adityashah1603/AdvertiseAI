-- Phase 3 backlog item: inspiration files are selected by filename on a
-- request (requests.inspirations) but nothing ever fetches them into a
-- sandbox (worker/hydration/generation.py's own docstring already flagged
-- this). ROADMAP.md SS3.2 calls out that inspirations/ is still on the
-- older shared-prefix pattern and is "worth doing before it matters for
-- real (inspirations once request-attached selection is built)" - this is
-- that moment, so it gets the same per-tenant-bucket treatment brand-kit/
-- jobs already have, for the same isolation reasoning (onboarding.py).
alter table tenants add column inspirations_bucket text unique;
