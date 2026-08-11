"""
The one shared definition of how a request's Storage path is named -
imported by every place that reads or writes one (upload_urls.py,
execute_run.py, generation.py's edit-context fetch, the dev test scripts)
so the convention can never silently drift between a writer and a reader.

Mirrors the bucket-naming decision (onboarding.py): a human-readable slug
(here, the campaign name) plus the id's own first 8 hex characters for
guaranteed uniqueness - never a fabricated id, never something a caller has
to remember to keep in sync, since it's derived fresh from the same
campaign/request_id every time this is called.
"""
import re

_SLUG_MAX_LEN = 60


def _slugify(text):
    text = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (text or "untitled")[:_SLUG_MAX_LEN]


def request_folder(campaign, request_id):
    short_id = request_id.split("-")[0]
    return f"{_slugify(campaign)}-{short_id}"


def revision_prefix(campaign, request_id, revision_number):
    return f"{request_folder(campaign, request_id)}/revisions/{revision_number}"
