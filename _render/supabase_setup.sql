-- MRA SEC Map Builder - shared placements table.
-- Run this once in your Supabase project (SQL Editor -> New query -> Run).
-- Then open sec_map.html, click the "local only" label, and paste your
-- project URL + anon key (Project Settings -> API).

create table if not exists placements (
  cell        text primary key,          -- "ew,ns,layer", e.g. "55,50,b"
  filename    text not null,             -- SEC filename placed there
  mp_x        int  not null,             -- East-West
  mp_y        int  not null,             -- North-South
  layer       text not null,            -- 'a' under | 'b' ground | 'c' upper
  mp_z        int,
  place_name  text,                      -- .ods Layout name for the cell
  updated_by  text,
  updated_at  timestamptz default now()
);

-- Community editing: anon key may read + write. (Map data is not sensitive.)
alter table placements enable row level security;

drop policy if exists "community read"  on placements;
drop policy if exists "community write" on placements;
create policy "community read"  on placements for select using (true);
create policy "community write" on placements for all    using (true) with check (true);

-- Live sync so everyone sees edits in real time.
alter publication supabase_realtime add table placements;
