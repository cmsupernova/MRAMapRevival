-- Shared persistence for the interior / cluster editor (sec_cluster.html).
-- Separate from `placements` (the world grid) because interiors are NOT on the
-- world coordinate system - they use a local lx,ly grid per cluster.
-- Run this once in the Supabase SQL editor (in addition to supabase_setup.sql).

create table if not exists cluster_cells (
  id          text primary key,          -- "cluster:lx,ly,layer", e.g. "orc:2,1,b"
  cluster     text not null,             -- region key, e.g. "orc"
  lx          int  not null,             -- local east-west cell
  ly          int  not null,             -- local north-south cell (down = south)
  layer       text not null,             -- 'a' under | 'b' ground | 'c' upper
  filename    text not null,             -- SEC filename placed there
  updated_by  text,
  updated_at  timestamptz default now()
);

alter table cluster_cells enable row level security;

drop policy if exists "community read"  on cluster_cells;
drop policy if exists "community write" on cluster_cells;
create policy "community read"  on cluster_cells for select using (true);
create policy "community write" on cluster_cells for all    using (true) with check (true);

alter publication supabase_realtime add table cluster_cells;
