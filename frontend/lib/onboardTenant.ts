import type { SupabaseClient } from "@supabase/supabase-js";
import type { Tenant } from "./types";

// TypeScript port of supabase/onboarding.py's onboard_tenant() - same
// behavior, same bucket-naming convention (brandkit-{slug}-{short_id} /
// jobs-{slug}-{short_id}), same idempotent-by-slug semantics. Ported rather
// than shelled out to from a Node request handler because the logic itself
// is ~30 lines; the goal is one BEHAVIOR onboarding follows, not literally
// one implementation across a language boundary. Any drift between this and
// the Python version would defeat the point, so keep them in lockstep by
// hand if either changes.
//
// This is the real "a brand-new company shows up in the UI" path
// (ROADMAP.md's own framing for onboarding.py) - the worker's
// seed.py/BRANDS list stays a dev convenience for the three
// already-known test brands, never required for a new one.

export type UploadFile = { relPath: string; data: Uint8Array; contentType?: string };

export async function onboardTenant(
  client: SupabaseClient,
  slug: string,
  name: string,
  files: UploadFile[]
): Promise<Pick<Tenant, "id" | "brand_kit_bucket" | "jobs_bucket">> {
  const { data: existingRows, error: selectErr } = await client
    .from("tenants")
    .select("*")
    .eq("slug", slug);
  if (selectErr) throw new Error(`tenant lookup failed: ${selectErr.message}`);

  let tenantId: string;
  let brandKitBucket: string;
  let jobsBucket: string;

  if (existingRows && existingRows.length > 0) {
    const tenant = existingRows[0] as Tenant;
    tenantId = tenant.id;
    brandKitBucket = tenant.brand_kit_bucket!;
    jobsBucket = tenant.jobs_bucket!;
  } else {
    const { data: inserted, error: insertErr } = await client
      .from("tenants")
      .insert({ slug, name })
      .select()
      .single();
    if (insertErr || !inserted) {
      throw new Error(`tenant insert failed: ${insertErr?.message}`);
    }
    tenantId = inserted.id as string;
    const shortId = tenantId.split("-")[0]; // the UUID's own first 8 hex chars, never a new id invented
    brandKitBucket = `brandkit-${slug}-${shortId}`;
    jobsBucket = `jobs-${slug}-${shortId}`;

    const { error: bkBucketErr } = await client.storage.createBucket(brandKitBucket, {
      public: false,
    });
    if (bkBucketErr) throw new Error(`brand-kit bucket create failed: ${bkBucketErr.message}`);
    const { error: jobsBucketErr } = await client.storage.createBucket(jobsBucket, {
      public: false,
    });
    if (jobsBucketErr) throw new Error(`jobs bucket create failed: ${jobsBucketErr.message}`);

    const { error: updateErr } = await client
      .from("tenants")
      .update({ brand_kit_bucket: brandKitBucket, jobs_bucket: jobsBucket })
      .eq("id", tenantId);
    if (updateErr) throw new Error(`tenant bucket-name update failed: ${updateErr.message}`);
  }

  for (const file of files) {
    const { error: uploadErr } = await client.storage
      .from(brandKitBucket)
      .upload(file.relPath, file.data, {
        upsert: true,
        contentType: file.contentType,
      });
    if (uploadErr) {
      throw new Error(`upload of '${file.relPath}' failed: ${uploadErr.message}`);
    }
  }

  return { id: tenantId, brand_kit_bucket: brandKitBucket, jobs_bucket: jobsBucket };
}
