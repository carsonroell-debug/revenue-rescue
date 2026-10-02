-- Revenue Rescue private persistence schema.
--
-- This is a deployment SQL reference, not a migration-history file.
-- Generate the real migration with the Supabase CLI when attaching a project.

create schema if not exists revenue_rescue;

revoke all on schema revenue_rescue from public;
revoke all on schema revenue_rescue from anon;
revoke all on schema revenue_rescue from authenticated;

create table if not exists revenue_rescue.audit_jobs (
  id uuid primary key,
  state jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists revenue_rescue.monitors (
  id uuid primary key,
  state jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table revenue_rescue.audit_jobs enable row level security;
alter table revenue_rescue.monitors enable row level security;

revoke all on revenue_rescue.audit_jobs from public, anon, authenticated;
revoke all on revenue_rescue.monitors from public, anon, authenticated;

create index if not exists revenue_rescue_audit_jobs_updated_idx
  on revenue_rescue.audit_jobs (updated_at desc);

create index if not exists revenue_rescue_monitors_updated_idx
  on revenue_rescue.monitors (updated_at desc);

comment on schema revenue_rescue is
  'Private server-side state for Revenue Rescue audits and monitors.';
