import Link from "next/link";
import { getServerSupabase } from "@/lib/supabase";

export const dynamic = "force-dynamic"; // always read the live tenant/request list, never cache

export default async function HomePage() {
  const client = getServerSupabase();

  const { data: tenants } = await client
    .from("tenants")
    .select("id, slug, name")
    .order("name", { ascending: true });

  const { data: recentRequests } = await client
    .from("requests")
    .select("id, campaign, created_at, tenant_id, tenants(name)")
    .order("created_at", { ascending: false })
    .limit(10);

  return (
    <div className="page narrow">
      <div className="hero-cta">
        <div>
          <h2>What do you want to build?</h2>
          <p>Describe a campaign, pick a brand, watch it run through the real pipeline.</p>
        </div>
        <Link href="/new-campaign">
          <button>New request</button>
        </Link>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Tenants</h2>
        {tenants && tenants.length > 0 ? (
          <ul className="tenant-list">
            {tenants.map((t) => (
              <li key={t.id}>
                <span>{t.name}</span>
                <span className="muted mono">{t.slug}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            No brands onboarded yet. <Link href="/onboard">Onboard one</Link> to get started.
          </p>
        )}
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Recent requests</h2>
        {recentRequests && recentRequests.length > 0 ? (
          <ul className="tenant-list">
            {recentRequests.map((r) => {
              const tenantName = Array.isArray(r.tenants)
                ? (r.tenants[0] as { name?: string } | undefined)?.name
                : (r.tenants as unknown as { name?: string } | null)?.name;
              return (
                <li key={r.id}>
                  <Link href={`/requests/${r.id}`}>{r.campaign ?? "(untitled campaign)"}</Link>
                  <span className="muted">{tenantName ?? "unknown brand"}</span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="muted">No campaigns submitted yet.</p>
        )}
      </div>
    </div>
  );
}
