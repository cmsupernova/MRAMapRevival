-- MRA SEC Map - unified multi-floor placements.
-- Run once in Supabase SQL Editor. The unified map writes only cells prefixed
-- with "unified:". Legacy four-tab rows (unprefixed / flat: / c2006: / n2011:)
-- are left untouched and ignored by the new map UI.

create table if not exists placements (
  cell        text primary key,          -- "unified:col,row,level" e.g. "unified:30,16,0"
  filename    text not null,             -- SEC filename or __cleared__
  mp_x        int  not null,             -- canvas col (unified) or EW (legacy)
  mp_y        int  not null,             -- canvas row (unified) or NS (legacy)
  layer       text not null,             -- integer level as text for unified ("0","1","-1")
                                         -- legacy a/b/c still valid for old rows
  mp_z        int,
  place_name  text,
  updated_by  text,
  updated_at  timestamptz default now()
);

alter table placements enable row level security;

drop policy if exists "community read"  on placements;
drop policy if exists "community write" on placements;
create policy "community read"  on placements for select using (true);
create policy "community write" on placements for all    using (true) with check (true);

-- Live sync (safe if already added)
do $$ begin
  alter publication supabase_realtime add table placements;
exception when duplicate_object then null;
end $$;

-- Optional helper view: only the authoritative unified namespace
create or replace view unified_placements as
  select
    cell,
    split_part(substr(cell, 9), ',', 1)::int as col,
    split_part(substr(cell, 9), ',', 2)::int as row,
    split_part(substr(cell, 9), ',', 3)::int as level,
    filename, place_name, updated_by, updated_at
  from placements
  where cell like 'unified:%';
