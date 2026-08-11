import type { NextConfig } from "next";

// Deliberately minimal - no rewrites/proxies to Supabase, E2B, Anthropic or
// OpenAI. Every credentialed call happens server-side inside a Route
// Handler (lib/supabase.ts), never via a client-exposed config value here.
const nextConfig: NextConfig = {};

export default nextConfig;
