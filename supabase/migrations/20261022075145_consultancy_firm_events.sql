-- 星際智囊團工作台。只允許伺服器用 secret／service_role key 存取；anon、authenticated 完全不能讀寫。

-- 公司金流以「事件」保存：每個派工、收款、付款動作一筆，依 seq 重播即可還原帳本。
create table if not exists public.consultancy_firm_events (
  id          bigint generated always as identity primary key,
  firm_id     text not null,
  seq         integer not null check (seq > 0),
  action      text not null,
  args        jsonb not null default '{}'::jsonb,
  actor       text,
  created_at  timestamptz not null default now(),
  unique (firm_id, seq)
);

alter table public.consultancy_firm_events enable row level security;
revoke all on public.consultancy_firm_events from anon, authenticated;
