-- Opportunity Radar v3 — proposta de schema multiusuário com PostGIS.
-- No Supabase, habilite PostGIS em um schema dedicado (ex.: gis/extensions)
-- e ajuste o prefixo das funções conforme o schema escolhido.

create table if not exists public.opportunities (
    id uuid primary key default gen_random_uuid(),
    source text not null,
    source_job_id text not null,
    company text,
    title text not null,
    description text,
    location_text text,
    location extensions.geography(point, 4326),
    workplace_type text,
    employment_type text,
    url text not null,
    published_at timestamptz,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    active boolean not null default true,
    raw_data jsonb not null default '{}'::jsonb,
    unique(source, source_job_id)
);

create index if not exists opportunities_location_gix
on public.opportunities using gist(location);

create table if not exists public.search_profiles (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    name text not null,
    course_ids text[] not null default '{}',
    intent_ids text[] not null default '{}',
    include_keywords text[] not null default '{}',
    exclude_keywords text[] not null default '{}',
    workplace_types text[] not null default '{}',
    preferred_countries text[] not null default '{}',
    home_location extensions.geography(point, 4326),
    max_distance_meters integer,
    allow_unknown_distance boolean not null default true,
    remote_ignores_distance boolean not null default true,
    minimum_score integer not null default 45,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.opportunity_course_scores (
    opportunity_id uuid references public.opportunities(id) on delete cascade,
    course_id text not null,
    score integer not null check(score between 0 and 100),
    primary key(opportunity_id, course_id)
);

create table if not exists public.opportunity_intents (
    opportunity_id uuid references public.opportunities(id) on delete cascade,
    intent_id text not null,
    primary key(opportunity_id, intent_id)
);

create or replace function public.nearby_opportunities(lat float, long float, max_results int default 100)
returns table (
    id uuid,
    title text,
    company text,
    location_text text,
    url text,
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
      o.url,
      extensions.st_distance(
        o.location,
        extensions.st_point(long, lat)::extensions.geography
      ) as dist_meters
    from public.opportunities o
    where o.active = true and o.location is not null
    order by o.location operator(extensions.<->) extensions.st_point(long, lat)::extensions.geography
    limit max_results;
$$;
