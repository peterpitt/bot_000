-- 星際智囊團工作台。只允許伺服器用 secret／service_role key 存取；anon、authenticated 完全不能讀寫。

-- 提案紀錄
create table if not exists public.consultancy_proposals (
  id          text primary key check (char_length(id) between 8 and 64),
  idea        text not null check (char_length(idea) <= 5000),
  input       jsonb not null default '{}'::jsonb,
  topics      text[] not null default '{}',
  advisors    text[] not null default '{}',
  result      jsonb,
  mvp_text    text not null default '',
  engine      text,
  created_by  text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index if not exists consultancy_proposals_updated_idx
  on public.consultancy_proposals (updated_at desc);

alter table public.consultancy_proposals enable row level security;
revoke all on public.consultancy_proposals from anon, authenticated;
