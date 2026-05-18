# Личный планер

Первая рабочая версия личного веб-планера на `Python + FastAPI`.

## Что уже есть

- главная страница с прогрессом дня
- календарь с цветной отметкой рабочих дней
- задачи и подзадачи
- цели и шаги к ним
- привычки с булевыми и числовыми отметками
- вес и параметры

## Как запустить

```bash
cd planner_app
../.venv/bin/uvicorn app.main:app --reload
```

После запуска открой:

`http://127.0.0.1:8000`

## Технологии

- `FastAPI`
- `Jinja2`
- `SQLModel`
- `SQLite`

## Supabase

Для следующего этапа уже подготовлены:

- `.env` c `SUPABASE_URL` и `SUPABASE_PUBLISHABLE_KEY`
- SQL-схема в [supabase/schema.sql](/Users/olesakolomina/Documents/New%20project/planner_app/supabase/schema.sql)
- инструкция в [supabase/README.md](/Users/olesakolomina/Documents/New%20project/planner_app/supabase/README.md)

## Публикация на Render

Проект подготовлен для деплоя через `Render`.

Что понадобится в Render:

- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `APP_SESSION_SECRET`

Если будешь создавать сервис вручную, используй:

- `Root Directory`: `planner_app`
- `Build Command`: `pip install -r requirements.txt`
- `Start Command`: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

В корень проекта также добавлен файл [render.yaml](/Users/olesakolomina/Documents/New%20project/render.yaml), чтобы Render мог подтянуть основные настройки автоматически.
