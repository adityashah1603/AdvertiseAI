-- Bug fix: deploy had no way to record WHICH canvas an operator meant to
-- publish. hydrate_deploy() fetched every canvas on the revision and
-- handed them all to the agent, which then had to improvise - sometimes
-- creating one ad, sometimes one per canvas, with no operator control over
-- which. Given Adstream genuinely only accepts one image per ad (a real,
-- confirmed constraint - DECISIONS.md), a deploy is now explicitly
-- single-canvas, chosen by the operator, not left to agent guesswork.
--
-- canvas_name on `runs` records what was asked for (deploy runs only -
-- null/unused for generate/edit); canvas_name on `deploys` records what
-- the completed attempt actually covers, so the UI can label it.
alter table runs add column canvas_name text;
alter table deploys add column canvas_name text;
