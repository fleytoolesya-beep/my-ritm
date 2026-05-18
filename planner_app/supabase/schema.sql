create extension if not exists "pgcrypto";

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.tasks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  task_date date not null,
  task_time text,
  status text not null default 'не начато',
  notes text,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.subtasks (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.tasks(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  completed boolean not null default false,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.goals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  category text not null,
  goal_type text not null,
  due_date date,
  notes text,
  completed boolean not null default false,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.goal_steps (
  id uuid primary key default gen_random_uuid(),
  goal_id uuid not null references public.goals(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  completed boolean not null default false,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.habits (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  habit_type text not null default 'boolean',
  frequency text not null default 'daily',
  schedule_details text,
  target_value double precision,
  unit text,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.habit_logs (
  id uuid primary key default gen_random_uuid(),
  habit_id uuid not null references public.habits(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  log_date date not null,
  completed boolean not null default false,
  numeric_value double precision,
  created_at timestamptz not null default timezone('utc', now()),
  unique (habit_id, log_date)
);

create table if not exists public.measurement_entries (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  entry_date date not null,
  weight double precision,
  waist double precision,
  chest double precision,
  hips double precision,
  glutes double precision,
  legs double precision,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.workdays (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  day date not null,
  created_at timestamptz not null default timezone('utc', now()),
  unique (user_id, day)
);

alter table public.profiles enable row level security;
alter table public.tasks enable row level security;
alter table public.subtasks enable row level security;
alter table public.goals enable row level security;
alter table public.goal_steps enable row level security;
alter table public.habits enable row level security;
alter table public.habit_logs enable row level security;
alter table public.measurement_entries enable row level security;
alter table public.workdays enable row level security;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute procedure public.handle_new_user();

create policy "profiles_select_own" on public.profiles
for select using (auth.uid() = id);

create policy "tasks_all_own" on public.tasks
for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "subtasks_all_own" on public.subtasks
for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "goals_all_own" on public.goals
for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "goal_steps_all_own" on public.goal_steps
for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "habits_all_own" on public.habits
for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "habit_logs_all_own" on public.habit_logs
for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "measurement_entries_all_own" on public.measurement_entries
for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "workdays_all_own" on public.workdays
for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
