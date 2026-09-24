-- Opportunity Radar — alvo PostgreSQL/PostGIS alinhado ao Checkpoint 4.
--
-- O CP4 separa oportunidade consolidada de anúncio source-native.
-- Este arquivo descreve o modelo a ser materializado no CP5.
-- Tabelas pessoais (usuários, presets, favoritos e candidaturas) ficam para CP7/CP8.
--
-- No Supabase, PostGIS pode viver em um schema dedicado (ex.: extensions).
-- Ajuste o prefixo das funções/tipos conforme a instalação.

create table if not exists public.opportunities (
    id uuid primary key default gen_random_uuid(),
    company text not null default '',
    title text not null default '',
    description text not null default '',
    location_text text not null default '',
    location extensions.geography(point, 4326),
    location_confidence text,
    workplace_type text,
    employment_type text,
    salary text,
    published_at timestamptz,
    canonical_url text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
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
    last_full_run boolean not null default false,
    last_coverage text not null default 'unknown',
    last_run_at timestamptz,
    primary key(source, scope_key)
);

create or replace function public.nearby_opportunities(
    lat float,
    long float,
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
    order by
      o.location operator(extensions.<->)
      extensions.st_point(long, lat)::extensions.geography
    limit max_results;
$$;
