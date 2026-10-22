-- 帳務稽核軌跡不可修改或刪除（更正請新增反向事件）
create or replace function public.consultancy_block_event_changes()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'consultancy_firm_events is append-only';
end;
$$;

drop trigger if exists consultancy_firm_events_append_only on public.consultancy_firm_events;
create trigger consultancy_firm_events_append_only
  before update or delete on public.consultancy_firm_events
  for each row execute function public.consultancy_block_event_changes();

revoke execute on function public.consultancy_block_event_changes() from public, anon, authenticated;
