"""
The one place that knows how to actually create an E2B sandbox.

FINDING (2026-08-11): execute_run.py called `Sandbox.create(template=...,
timeout=...)` - a classmethod that does not exist on `e2b==1.0.5` (the
version this project's own scripts/requirements.txt pins, and the one that
was actually installed). That SDK version constructs a sandbox via
`Sandbox(...)` directly; `Sandbox.create` was apparently API from a
different/older e2b release the call site was written against and never
verified against the pinned version. The same wrong call was duplicated in
test_sandbox_mechanics.py, so fixing one call site would still have left
the other broken - a second, independent way to hit the exact same bug.

Centralizing sandbox creation here means every caller in the system - the
real orchestrator, any future test/debug script - goes through one function
that matches whatever e2b API is actually installed. If e2b's constructor
signature changes again, there is exactly one place to update, not N call
sites that can silently drift out of sync with each other (same reasoning
as storage_paths.py's revision_prefix() being the one shared path
definition, or onboarding.py's onboard_tenant() being the one shared
onboarding implementation).

Disqualifier #2 (ROADMAP.md SS1) - no tenant- or task-specific sandbox
identity - is enforced here, not left to each caller to remember: this
function accepts only `template` and `timeout`, never a `metadata` or
`envs` kwarg that could carry a tenant/task name into the sandbox's own
identity. A caller cannot accidentally leak identifying metadata into a
sandbox through this function because the function doesn't accept it.
"""
from e2b import Sandbox


def create_sandbox(template=None, timeout=None):
    """Create a fresh, anonymous E2B sandbox. No tenant/task-identifying
    metadata is ever attached - the sandbox's only identity is the opaque
    id E2B itself issues (`sandbox.sandbox_id`)."""
    return Sandbox(template=template, timeout=timeout)
