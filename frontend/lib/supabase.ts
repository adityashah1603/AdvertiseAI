import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// Server-only. Imported exclusively from Route Handlers (app/api/**) and
// server-side helpers (onboardTenant.ts) - never from a "use client"
// component, never re-exported through a NEXT_PUBLIC_ var. This is the same
// trust boundary supabase/onboarding.py's get_client() enforces on the
// Python side: the service-role key stays on the trusted side, full stop.
let cached: SupabaseClient | null = null;

export function getServerSupabase(): SupabaseClient {
  if (cached) return cached;

  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) {
    throw new Error(
      "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set - see frontend/.env.example"
    );
  }

  cached = createClient(url, key, {
    auth: { persistSession: false },
  });
  return cached;
}
