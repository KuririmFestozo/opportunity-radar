-- CP5-A — PostgreSQL/PostGIS catalog schema.
-- Idempotent bootstrap for a dedicated Opportunity Radar database.

create schema if not exists extensions;
create extension if not exists postgis with schema extensions;

create table if not exists public.opportunities (
    id uuid primary key,
    company text not null default '',
    title text not null default '',
    description text not null default '',
    location_text text not null default '',
    location extensions.geography(Point, 4326),
    location_confidence text,
    workplace_type text,
    employment_type text,
    salary text,
    published_at timestamptz,
    canonical_url text,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

create index if not exists opportunities_location_gix
on public.opportunities using gist(location);

create table if not exists public.source_postings (
    source text not null,
    source_job_id text not null,
    opportunity_id uuid not null references public.opportunities(id) on delete restrict,
    url text not null default '',
    source_type text not null default 'official_api',
    normalized_job_json jsonb not null default '{}'::jsonb,
    raw_hash text not null,
    processing_version text not null,
    first_seen_at timestamptz not null,
    last_seen_at timestamptz not null,
    last_checked_at timestamptz,
    last_changed_at timestamptz not null,
    is_active boolean not null default true,
    missing_since timestamptz,
    inactive_at timestamptz,
    miss_count integer not null default 0 check (miss_count >= 0),
    seen_count integer not null default 0 check (seen_count >= 0),
    association_method text not null default 'identity',
    associated_at timestamptz,
    primary key(source, source_job_id)
);

create index if not exists source_postings_opportunity_idx
on public.source_postings(opportunity_id);
create index if not exists source_postings_active_idx
on public.source_postings(is_active);
create index if not exists source_postings_last_seen_idx
on public.source_postings(last_seen_at);

create table if not exists public.opportunity_course_scores (
    opportunity_id uuid not null references public.opportunities(id) on delete cascade,
    course_id text not null,
    score integer not null check(score between 0 and 100),
    primary key(opportunity_id, course_id)
);

create table if not exists public.opportunity_intents (
    opportunity_id uuid not null references public.opportunities(id) on delete cascade,
    intent_id text not null,
    primary key(opportunity_id, intent_id)
);

create table if not exists public.discovery_state (
    source text not null,
    source_job_id text not null,
    scope_status text not null default 'catalog',
    first_seen_at timestamptz not null,
    last_seen_at timestamptz not null,
    last_checked_at timestamptz not null,
    seen_count integer not null default 1 check (seen_count >= 1),
    primary key(source, source_job_id)
);

create index if not exists discovery_state_source_idx
on public.discovery_state(source);
create index if not exists discovery_state_scope_status_idx
on public.discovery_state(scope_status);

create table if not exists public.collection_scopes (
    source text not null,
    scope_key text not null,
    successful_runs integer not null default 0 check (successful_runs >= 0),
    last_full_run integer not null default 0 check (last_full_run >= 0),
    last_coverage text not null default 'unknown',
    last_run_at timestamptz,
    primary key(source, scope_key)
);

alter table public.opportunities enable row level security;
alter table public.source_postings enable row level security;
alter table public.opportunity_course_scores enable row level security;
alter table public.opportunity_intents enable row level security;
alter table public.discovery_state enable row level security;
alter table public.collection_scopes enable row level security;

create or replace function public.nearby_opportunities(
    lat float,
    long float,
    radius_meters float default 50000,
    max_results int default 100
)
returns table (
    id uuid,
    title text,
    company text,
    location_text text,
    canonical_url text,
    dist_meters float
)
set search_path = ''
language sql
stable
as $$
    select
      o.id,
      o.title,
      o.company,
      o.location_text,
      o.canonical_url,
      extensions.st_distance(
        o.location,
        extensions.st_point(long, lat)::extensions.geography
      ) as dist_meters
    from public.opportunities o
    where o.location is not null
      and exists (
        select 1
        from public.source_postings sp
        where sp.opportunity_id = o.id
          and sp.is_active = true
      )
      and extensions.st_dwithin(
        o.location,
        extensions.st_point(long, lat)::extensions.geography,
        radius_meters
      )
    order by
      o.location operator(extensions.<->)
      extensions.st_point(long, lat)::extensions.geography
    limit greatest(1, least(max_results, 1000));
$$;
