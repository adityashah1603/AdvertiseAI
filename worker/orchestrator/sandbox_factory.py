"""
The one place that knows how to actually create an E2B sandbox.

FINDING (2026-08-11): execute_run.py called `Sandbox.create(template=...,
timeout=...)` - a classmethod that does not exist on `e2b==1.0.5` (the
version this project's own scripts/requirements.txt pins, and the one that
was actually installed at the time). That SDK version constructs a sandbox
via `Sandbox(...)` directly. Fixed then by switching this function to
`Sandbox(template=template, timeout=timeout)`.

FINDING (2026-08-11, later the same day): the SAME bug recurred, inverted.
worker/orchestrator/ never had its own requirements.txt (unlike every other
venv in this repo), so `e2b` was installed into it unpinned and had since
resolved to `2.38.0` - a major-version jump from the 1.0.5 every other
reference in the repo assumed. In 2.38.0, direct `Sandbox(...)` construction
is for RECONNECTING to an already-running sandbox by id (its `__init__`
takes `sandbox_id`, `envd_version`, etc.) - creating a new one is
`Sandbox.create(template=..., timeout=..., ...)`, a classmethod. Caught
because test_concurrency_edit.py's clean, single-dispatcher re-run failed
all 4 real edit runs with `SandboxBase.__init__() got an unexpected keyword
argument 'template'`, not because anyone remembered to check the installed
version against the pin. Fixed by switching back to `Sandbox.create(...)`
AND, this time, adding worker/orchestrator/requirements.txt pinning the
version this function is now known to work against, so the two can't drift
apart silently a third time.

Centralizing sandbox creation here means every caller in the system - the
real orchestrator, any future test/debug script - goes through one function
that matches whatever e2b API is actually pinned for this venv. If e2b's
constructor signature changes again, there is exactly one place to update,
not N call sites that can silently drift out of sync with each other (same
reasoning as storage_paths.py's revision_prefix() being the one shared path
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
    return Sandbox.create(template=template, timeout=timeout)
