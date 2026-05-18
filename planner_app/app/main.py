from __future__ import annotations

from calendar import monthcalendar
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Field, Session, SQLModel, create_engine, delete, func, select

from .config import get_settings
from .supabase_client import get_supabase_client


BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR.parent / "planner.db"
engine = create_engine(
    f"sqlite:///{DB_FILE}", echo=False, connect_args={"check_same_thread": False}
)


class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    task_date: date
    task_time: Optional[str] = None
    status: str = "не начато"
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Subtask(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id")
    title: str
    completed: bool = False


class Goal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    category: str
    goal_type: str
    due_date: Optional[date] = None
    notes: Optional[str] = None
    completed: bool = False


class GoalStep(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    goal_id: int = Field(foreign_key="goal.id")
    title: str
    completed: bool = False


class Habit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    habit_type: str = "boolean"
    frequency: str = "daily"
    schedule_details: Optional[str] = None
    target_value: Optional[float] = None
    unit: Optional[str] = None


class HabitLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    habit_id: int = Field(foreign_key="habit.id")
    log_date: date
    completed: bool = False
    numeric_value: Optional[float] = None


class MeasurementEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entry_date: date
    weight: Optional[float] = None
    waist: Optional[float] = None
    chest: Optional[float] = None
    hips: Optional[float] = None
    glutes: Optional[float] = None
    legs: Optional[float] = None


class Workday(SQLModel, table=True):
    day: date = Field(primary_key=True)


STATUS_OPTIONS = ["не начато", "в процессе", "выполнено", "отложено", "отменено"]
GOAL_TYPES = ["краткосрочная", "месячная", "годовая"]
GOAL_CATEGORIES = ["работа", "здоровье", "финансы", "личное", "другое"]
HABIT_FREQUENCIES = ["daily", "weekdays", "interval"]
HABIT_FREQUENCY_LABELS = {
    "daily": "каждый день",
    "weekdays": "по дням недели",
    "interval": "раз в несколько дней",
}
MONTH_LABELS = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}

app = FastAPI(title="Личный планер")
settings = get_settings()
app.add_middleware(SessionMiddleware, secret_key=settings.app_session_secret)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


init_db()


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def parse_date(value: Optional[str], default: Optional[date] = None) -> Optional[date]:
    if not value:
        return default
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def redirect_to(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def get_current_user(request: Request) -> Optional[dict]:
    session_data = request.scope.get("session", {})
    user_id = session_data.get("user_id")
    email = session_data.get("user_email")
    access_token = session_data.get("access_token")
    refresh_token = session_data.get("refresh_token")
    if not user_id or not email:
        return None
    return {
        "id": user_id,
        "email": email,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


def format_delta(value: Optional[float]) -> str:
    if value is None:
        return "—"
    rounded = round(value, 1)
    if rounded == 0:
        return "0"
    if float(rounded).is_integer():
        return f"{int(rounded):+d}"
    return f"{rounded:+.1f}"


templates.env.globals["get_current_user"] = get_current_user
templates.env.globals["format_delta"] = format_delta


def set_auth_session(request: Request, auth_response) -> None:
    if not getattr(auth_response, "session", None) or not getattr(auth_response, "user", None):
        return
    request.session["user_id"] = auth_response.user.id
    request.session["user_email"] = auth_response.user.email or ""
    request.session["access_token"] = auth_response.session.access_token
    request.session["refresh_token"] = auth_response.session.refresh_token


def auth_error_message(exc: Exception, fallback: str) -> str:
    message = str(exc)
    lowered = message.lower()
    if "email not confirmed" in lowered or "email_not_confirmed" in lowered:
        return "Почта еще не подтверждена. Открой письмо от Supabase и подтверди email, потом войди."
    if "invalid login credentials" in lowered:
        return "Не удалось войти. Проверь email и пароль."
    if "user already registered" in lowered:
        return "Такой email уже зарегистрирован. Попробуй войти или восстановить пароль позже."
    return fallback


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    return await call_next(request)


def require_auth(request: Request) -> Optional[RedirectResponse]:
    if get_current_user(request) is None:
        return redirect_to("/login")
    return None


def frequency_label(code: str) -> str:
    return HABIT_FREQUENCY_LABELS.get(code, code)


def get_authenticated_supabase(request: Request):
    user = get_current_user(request)
    if user is None:
        return None
    client = get_supabase_client()
    if client is None:
        return None
    access_token = user.get("access_token")
    refresh_token = user.get("refresh_token")
    if access_token and refresh_token:
        client.auth.set_session(access_token, refresh_token)
    return client


def task_object_from_row(row: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=row["id"],
        title=row["title"],
        task_date=parse_date(row["task_date"]),
        task_time=row.get("task_time"),
        status=row.get("status", "не начато"),
        notes=row.get("notes"),
        created_at=row.get("created_at"),
    )


def subtask_object_from_row(row: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=row["id"],
        task_id=row["task_id"],
        title=row["title"],
        completed=row.get("completed", False),
    )


def goal_object_from_row(row: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=row["id"],
        title=row["title"],
        category=row["category"],
        goal_type=row["goal_type"],
        due_date=parse_date(row["due_date"]) if row.get("due_date") else None,
        notes=row.get("notes"),
        completed=row.get("completed", False),
    )


def goal_step_object_from_row(row: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=row["id"],
        goal_id=row["goal_id"],
        title=row["title"],
        completed=row.get("completed", False),
    )


def habit_object_from_row(row: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=row["id"],
        title=row["title"],
        habit_type=row.get("habit_type", "boolean"),
        frequency=row.get("frequency", "daily"),
        schedule_details=row.get("schedule_details"),
        target_value=row.get("target_value"),
        unit=row.get("unit"),
    )


def habit_log_object_from_row(row: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=row["id"],
        habit_id=row["habit_id"],
        log_date=parse_date(row["log_date"]),
        completed=row.get("completed", False),
        numeric_value=row.get("numeric_value"),
    )


def measurement_object_from_row(row: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=row["id"],
        entry_date=parse_date(row["entry_date"]),
        weight=row.get("weight"),
        waist=row.get("waist"),
        chest=row.get("chest"),
        hips=row.get("hips"),
        glutes=row.get("glutes"),
        legs=row.get("legs"),
        created_at=row.get("created_at"),
    )


def fetch_tasks(request: Request, task_date: Optional[date] = None) -> list[SimpleNamespace]:
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return []
    query = client.table("tasks").select("*").eq("user_id", user["id"])
    if task_date is not None:
        query = query.eq("task_date", task_date.isoformat())
    response = query.order("task_date").order("task_time").execute()
    return [task_object_from_row(row) for row in (response.data or [])]


def fetch_subtasks(request: Request, task_ids: Optional[list[str]] = None) -> list[SimpleNamespace]:
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return []
    query = client.table("subtasks").select("*").eq("user_id", user["id"])
    if task_ids:
        query = query.in_("task_id", task_ids)
    response = query.order("created_at").execute()
    return [subtask_object_from_row(row) for row in (response.data or [])]


def fetch_goals(request: Request) -> list[SimpleNamespace]:
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return []
    response = (
        client.table("goals")
        .select("*")
        .eq("user_id", user["id"])
        .order("completed")
        .order("created_at", desc=True)
        .execute()
    )
    return [goal_object_from_row(row) for row in (response.data or [])]


def fetch_goal_steps(request: Request, goal_ids: Optional[list[str]] = None) -> list[SimpleNamespace]:
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return []
    query = client.table("goal_steps").select("*").eq("user_id", user["id"])
    if goal_ids:
        query = query.in_("goal_id", goal_ids)
    response = query.order("created_at").execute()
    return [goal_step_object_from_row(row) for row in (response.data or [])]


def fetch_habits(request: Request) -> list[SimpleNamespace]:
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return []
    response = (
        client.table("habits")
        .select("*")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .execute()
    )
    return [habit_object_from_row(row) for row in (response.data or [])]


def fetch_habit_logs(
    request: Request,
    habit_ids: Optional[list[str]] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> list[SimpleNamespace]:
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return []
    query = client.table("habit_logs").select("*").eq("user_id", user["id"])
    if habit_ids:
        query = query.in_("habit_id", habit_ids)
    if from_date:
        query = query.gte("log_date", from_date.isoformat())
    if to_date:
        query = query.lte("log_date", to_date.isoformat())
    response = query.order("log_date", desc=True).execute()
    return [habit_log_object_from_row(row) for row in (response.data or [])]


def fetch_measurements(
    request: Request,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> list[SimpleNamespace]:
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return []
    query = client.table("measurement_entries").select("*").eq("user_id", user["id"])
    if from_date:
        query = query.gte("entry_date", from_date.isoformat())
    if to_date:
        query = query.lte("entry_date", to_date.isoformat())
    response = query.order("entry_date", desc=True).order("created_at", desc=True).execute()
    return [measurement_object_from_row(row) for row in (response.data or [])]


def habit_stats_from_logs(habits: list[SimpleNamespace], logs: list[SimpleNamespace]) -> tuple[dict, dict]:
    logs_by_habit: dict[str, list[SimpleNamespace]] = {}
    for log in logs:
        logs_by_habit.setdefault(log.habit_id, []).append(log)

    stats = {}
    for habit in habits:
        habit_logs = logs_by_habit.get(habit.id, [])
        total_days = len(habit_logs)
        if habit.habit_type == "boolean":
            completed_days = sum(1 for log in habit_logs if log.completed)
            percent = round((completed_days / total_days) * 100) if total_days else 0
            streak = 0
            for log in sorted(habit_logs, key=lambda item: item.log_date, reverse=True):
                if log.completed:
                    streak += 1
                else:
                    break
        else:
            completed_days = sum(
                1
                for log in habit_logs
                if log.numeric_value is not None
                and habit.target_value is not None
                and log.numeric_value >= habit.target_value
            )
            percent = round((completed_days / total_days) * 100) if total_days else 0
            streak = 0
            for log in sorted(habit_logs, key=lambda item: item.log_date, reverse=True):
                if (
                    log.numeric_value is not None
                    and habit.target_value is not None
                    and log.numeric_value >= habit.target_value
                ):
                    streak += 1
                else:
                    break
        stats[habit.id] = {"percent": percent, "streak": streak}
    return logs_by_habit, stats


def fetch_workdays(request: Request, from_date: Optional[date] = None, to_date: Optional[date] = None) -> list[SimpleNamespace]:
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return []
    query = client.table("workdays").select("*").eq("user_id", user["id"])
    if from_date:
        query = query.gte("day", from_date.isoformat())
    if to_date:
        query = query.lte("day", to_date.isoformat())
    response = query.order("day").execute()
    return [SimpleNamespace(id=row["id"], day=parse_date(row["day"])) for row in (response.data or [])]


def analytics_context(request: Request, today: date) -> dict:
    week_start = today - timedelta(days=6)
    month_start = today.replace(day=1)
    week_tasks = fetch_tasks(request)
    week_tasks = [task for task in week_tasks if week_start <= task.task_date <= today]
    habit_logs = fetch_habit_logs(request, from_date=week_start, to_date=today)
    workdays = fetch_workdays(request, from_date=month_start, to_date=today)
    all_measurements = fetch_measurements(request)
    month_measurements = [entry for entry in all_measurements if entry.entry_date >= month_start]
    current_measurement = all_measurements[0] if all_measurements else None
    month_first_measurement = month_measurements[-1] if month_measurements else None

    tasks_week_completed = sum(1 for task in week_tasks if task.status == "выполнено")
    habits_week_completed = sum(
        1
        for log in habit_logs
        if log.completed or (log.numeric_value is not None and log.numeric_value > 0)
    )
    weight_change = None
    if (
        current_measurement
        and month_first_measurement
        and current_measurement.id != month_first_measurement.id
        and current_measurement.weight is not None
        and month_first_measurement.weight is not None
    ):
        weight_change = round(current_measurement.weight - month_first_measurement.weight, 1)

    return {
        "tasks_week_completed": tasks_week_completed,
        "tasks_week_total": len(week_tasks),
        "habits_week_completed": habits_week_completed,
        "workdays_this_month": len(workdays),
        "weight_change": weight_change,
    }


def dashboard_context(request: Request) -> dict:
    today = date.today()
    tasks_today = fetch_tasks(request, today)
    goals = fetch_goals(request)[:4]
    goal_steps = fetch_goal_steps(request, [goal.id for goal in goals]) if goals else []
    habits = fetch_habits(request)
    logs = fetch_habit_logs(request, [habit.id for habit in habits], today, today) if habits else []
    workdays_today = fetch_workdays(request, today, today)
    measurements = fetch_measurements(request)
    last_measurement = measurements[0] if measurements else None

    logs_by_habit = {log.habit_id: log for log in logs}
    completed_tasks = sum(1 for task in tasks_today if task.status == "выполнено")
    progress = round((completed_tasks / len(tasks_today)) * 100) if tasks_today else 0
    focus_task = next((task for task in tasks_today if task.status != "выполнено"), None)

    habits_today = []
    for habit in habits:
        log = logs_by_habit.get(habit.id)
        habits_today.append(
            {"habit": habit, "log": log, "frequency_label": frequency_label(habit.frequency)}
        )

    steps_by_goal: dict[int, list[GoalStep]] = {}
    for step in goal_steps:
        steps_by_goal.setdefault(step.goal_id, []).append(step)

    goal_summaries = []
    for goal in goals:
        current_steps = steps_by_goal.get(goal.id, [])
        completed_steps = sum(1 for step in current_steps if step.completed)
        total_steps = len(current_steps)
        goal_progress = round((completed_steps / total_steps) * 100) if total_steps else (
            100 if goal.completed else 0
        )
        goal_summaries.append(
            {
                "goal": goal,
                "completed_steps": completed_steps,
                "total_steps": total_steps,
                "progress": goal_progress,
            }
        )

    return {
        "today": today,
        "tasks_today": tasks_today,
        "goal_summaries": goal_summaries,
        "habits_today": habits_today,
        "progress": progress,
        "is_workday": bool(workdays_today),
        "last_measurement": last_measurement,
        "focus_task": focus_task,
        **analytics_context(request, today),
    }


def get_calendar_data(request: Request, year: int, month: int) -> dict:
    weeks = monthcalendar(year, month)
    start = date(year, month, 1)
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    end = next_month - timedelta(days=1)

    workdays = fetch_workdays(request, start, end)
    tasks = fetch_tasks(request)
    tasks = [task for task in tasks if start <= task.task_date <= end]
    habits = fetch_habits(request)
    logs = fetch_habit_logs(request, [habit.id for habit in habits], start, end) if habits else []

    workday_set = {item.day for item in workdays}
    task_map: dict[date, int] = {}
    for task in tasks:
        task_map[task.task_date] = task_map.get(task.task_date, 0) + 1
    habit_map: dict[date, int] = {}
    for log in logs:
        habit_map[log.log_date] = habit_map.get(log.log_date, 0) + 1
    today = date.today()

    calendar_days = []
    for week in weeks:
        row = []
        for day_num in week:
            if day_num == 0:
                row.append(None)
                continue
            current_day = date(year, month, day_num)
            row.append(
                {
                    "date": current_day,
                    "day_num": day_num,
                    "is_today": current_day == today,
                    "is_workday": current_day in workday_set,
                    "task_count": task_map.get(current_day, 0),
                    "habit_count": habit_map.get(current_day, 0),
                }
            )
        calendar_days.append(row)

    prev_month_date = start - timedelta(days=1)
    next_month_date = end + timedelta(days=1)
    return {
        "weeks": calendar_days,
        "title": f"{MONTH_LABELS[month]} {year}",
        "month": month,
        "year": year,
        "prev_year": prev_month_date.year,
        "prev_month": prev_month_date.month,
        "next_year": next_month_date.year,
        "next_month": next_month_date.month,
    }


@app.get("/")
def root() -> RedirectResponse:
    return redirect_to("/dashboard")


@app.get("/login")
def login_page(request: Request, error: Optional[str] = None, message: Optional[str] = None):
    return templates.TemplateResponse(
        request,
        "auth.html",
        {"request": request, "mode": "login", "error": error, "message": message},
    )


@app.post("/login")
def login_action(request: Request, email: str = Form(...), password: str = Form(...)):
    client = get_supabase_client()
    if client is None:
        return templates.TemplateResponse(
            request,
            "auth.html",
            {
                "request": request,
                "mode": "login",
                "error": "Supabase пока не настроен.",
                "message": None,
            },
            status_code=500,
        )
    try:
        auth_response = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "auth.html",
            {
                "request": request,
                "mode": "login",
                "error": auth_error_message(exc, "Не удалось войти. Проверь email и пароль."),
                "message": None,
            },
            status_code=400,
        )

    set_auth_session(request, auth_response)
    return redirect_to("/dashboard")


@app.get("/register")
def register_page(request: Request, error: Optional[str] = None, message: Optional[str] = None):
    return templates.TemplateResponse(
        request,
        "auth.html",
        {"request": request, "mode": "register", "error": error, "message": message},
    )


@app.post("/register")
def register_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_repeat: str = Form(...),
):
    if password != password_repeat:
        return templates.TemplateResponse(
            request,
            "auth.html",
            {
                "request": request,
                "mode": "register",
                "error": "Пароли не совпадают.",
                "message": None,
            },
            status_code=400,
        )

    client = get_supabase_client()
    if client is None:
        return templates.TemplateResponse(
            request,
            "auth.html",
            {
                "request": request,
                "mode": "register",
                "error": "Supabase пока не настроен.",
                "message": None,
            },
            status_code=500,
        )

    try:
        auth_response = client.auth.sign_up({"email": email, "password": password})
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "auth.html",
            {
                "request": request,
                "mode": "register",
                "error": auth_error_message(
                    exc,
                    "Не удалось зарегистрироваться. Возможно, такой email уже используется.",
                ),
                "message": None,
            },
            status_code=400,
        )

    if getattr(auth_response, "session", None) and getattr(auth_response, "user", None):
        set_auth_session(request, auth_response)
        return redirect_to("/dashboard")

    return templates.TemplateResponse(
        request,
        "auth.html",
        {
            "request": request,
            "mode": "login",
            "error": None,
            "message": "Аккаунт создан. Если включено подтверждение почты, сначала подтверди email, затем войди.",
        },
    )


@app.get("/logout")
def logout_action(request: Request):
    client = get_supabase_client()
    if client is not None:
        try:
            client.auth.sign_out()
        except Exception:
            pass
    request.session.clear()
    return redirect_to("/login")


@app.get("/dashboard")
def dashboard(request: Request):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    return templates.TemplateResponse(
        request, "dashboard.html", {"request": request, **dashboard_context(request)}
    )


@app.post("/dashboard/tasks/{task_id}/toggle")
def toggle_task_from_dashboard(request: Request, task_id: str) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    if client is not None:
        response = client.table("tasks").select("id,status").eq("id", str(task_id)).limit(1).execute()
        if response.data:
            current = response.data[0]
            new_status = "не начато" if current["status"] == "выполнено" else "выполнено"
            client.table("tasks").update({"status": new_status}).eq("id", str(task_id)).execute()
    return redirect_to("/dashboard")


@app.post("/dashboard/habits/{habit_id}/toggle")
def toggle_habit_from_dashboard(request: Request, habit_id: str) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    today = date.today()
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    response = (
        client.table("habit_logs")
        .select("*")
        .eq("habit_id", habit_id)
        .eq("user_id", user["id"])
        .eq("log_date", today.isoformat())
        .limit(1)
        .execute()
    )
    if response.data:
        current = response.data[0]
        client.table("habit_logs").update({"completed": not current.get("completed", False)}).eq(
            "id", current["id"]
        ).eq("user_id", user["id"]).execute()
    else:
        client.table("habit_logs").insert(
            {
                "habit_id": habit_id,
                "user_id": user["id"],
                "log_date": today.isoformat(),
                "completed": True,
                "numeric_value": None,
            }
        ).execute()
    return redirect_to("/dashboard")


@app.post("/dashboard/habits/{habit_id}/status")
def set_habit_status_from_dashboard(
    request: Request, habit_id: str, completed: str = Form(...)
) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    today = date.today()
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    response = (
        client.table("habit_logs")
        .select("*")
        .eq("habit_id", habit_id)
        .eq("user_id", user["id"])
        .eq("log_date", today.isoformat())
        .limit(1)
        .execute()
    )
    payload = {
        "habit_id": habit_id,
        "user_id": user["id"],
        "log_date": today.isoformat(),
        "completed": completed == "true",
        "numeric_value": None,
    }
    if response.data:
        client.table("habit_logs").update(payload).eq("id", response.data[0]["id"]).eq(
            "user_id", user["id"]
        ).execute()
    else:
        client.table("habit_logs").insert(payload).execute()
    return redirect_to("/dashboard")


@app.post("/dashboard/habits/{habit_id}/increment")
def increment_habit_from_dashboard(
    request: Request, habit_id: str, delta: float = Form(...)
) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    today = date.today()
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    habit_response = (
        client.table("habits").select("*").eq("id", habit_id).eq("user_id", user["id"]).limit(1).execute()
    )
    if not habit_response.data:
        raise HTTPException(status_code=404)
    log_response = (
        client.table("habit_logs")
        .select("*")
        .eq("habit_id", habit_id)
        .eq("user_id", user["id"])
        .eq("log_date", today.isoformat())
        .limit(1)
        .execute()
    )
    current_value = 0.0
    if log_response.data:
        current_value = log_response.data[0].get("numeric_value") or 0.0
    payload = {
        "habit_id": habit_id,
        "user_id": user["id"],
        "log_date": today.isoformat(),
        "completed": False,
        "numeric_value": max(0, current_value + delta),
    }
    if log_response.data:
        client.table("habit_logs").update(payload).eq("id", log_response.data[0]["id"]).eq(
            "user_id", user["id"]
        ).execute()
    else:
        client.table("habit_logs").insert(payload).execute()
    return redirect_to("/dashboard")


@app.get("/calendar")
def calendar_page(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    today = date.today()
    year = year or today.year
    month = month or today.month
    context = get_calendar_data(request, year, month)
    return templates.TemplateResponse(
        request, "calendar.html", {"request": request, **context, "today": today}
    )


@app.get("/day/{day_value}")
def day_page(request: Request, day_value: str):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    selected_date = parse_date(day_value)
    tasks = fetch_tasks(request, selected_date)
    subtasks = fetch_subtasks(request, [task.id for task in tasks])
    habits = fetch_habits(request)
    logs = fetch_habit_logs(request, [habit.id for habit in habits], selected_date, selected_date) if habits else []
    workdays = fetch_workdays(request, selected_date, selected_date)

    subtasks_by_task: dict[str, list[SimpleNamespace]] = {}
    for subtask in subtasks:
        subtasks_by_task.setdefault(subtask.task_id, []).append(subtask)
    log_map = {log.habit_id: log for log in logs}
    habits_for_day = [
        {
            "habit": habit,
            "log": log_map.get(habit.id),
            "frequency_label": frequency_label(habit.frequency),
        }
        for habit in habits
    ]
    return templates.TemplateResponse(
        request,
        "day.html",
        {
            "request": request,
            "selected_date": selected_date,
            "tasks": tasks,
            "subtasks_by_task": subtasks_by_task,
            "habits_for_day": habits_for_day,
            "is_workday": bool(workdays),
        },
    )


@app.post("/workdays")
def add_workday(request: Request, day: str = Form(...)) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    workday_date = parse_date(day)
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    existing = (
        client.table("workdays")
        .select("id")
        .eq("user_id", user["id"])
        .eq("day", workday_date.isoformat())
        .limit(1)
        .execute()
    )
    if not existing.data:
        client.table("workdays").insert(
            {
                "user_id": user["id"],
                "day": workday_date.isoformat(),
            }
        ).execute()
    return redirect_to("/calendar")


@app.post("/workdays/delete")
def delete_workday(request: Request, day: str = Form(...)) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    workday_date = parse_date(day)
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is not None and user is not None:
        client.table("workdays").delete().eq("user_id", user["id"]).eq(
            "day", workday_date.isoformat()
        ).execute()
    return redirect_to("/calendar")


@app.get("/tasks")
def tasks_page(request: Request):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    tasks = fetch_tasks(request)
    subtasks = fetch_subtasks(request, [task.id for task in tasks])
    subtasks_by_task: dict[int, list[Subtask]] = {}
    for subtask in subtasks:
        subtasks_by_task.setdefault(subtask.task_id, []).append(subtask)
    return templates.TemplateResponse(
        request,
        "tasks.html",
        {
            "request": request,
            "tasks": tasks,
            "subtasks_by_task": subtasks_by_task,
            "status_options": STATUS_OPTIONS,
        },
    )


@app.get("/tasks/new")
def task_new_page(request: Request):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    return templates.TemplateResponse(
        request,
        "task_form.html",
        {
            "request": request,
            "task": None,
            "status_options": STATUS_OPTIONS,
            "subtasks": [],
            "default_date": date.today().isoformat(),
        },
    )


@app.post("/tasks")
def create_task(
    request: Request,
    title: str = Form(...),
    task_date: str = Form(...),
    task_time: str = Form(""),
    status: str = Form("не начато"),
    notes: str = Form(""),
    subtask_titles: str = Form(""),
) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    response = client.table("tasks").insert(
        {
            "user_id": user["id"],
            "title": title,
            "task_date": parse_date(task_date, date.today()).isoformat(),
            "task_time": task_time or None,
            "status": status,
            "notes": notes or None,
        }
    ).execute()
    task_id = response.data[0]["id"]
    for line in [item.strip() for item in subtask_titles.splitlines() if item.strip()]:
        client.table("subtasks").insert(
            {"task_id": task_id, "user_id": user["id"], "title": line}
        ).execute()
    return redirect_to("/tasks")


@app.get("/tasks/{task_id}/edit")
def task_edit_page(request: Request, task_id: str):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    task_response = client.table("tasks").select("*").eq("id", task_id).eq("user_id", user["id"]).limit(1).execute()
    if not task_response.data:
        raise HTTPException(status_code=404)
    task = task_object_from_row(task_response.data[0])
    subtasks = fetch_subtasks(request, [task_id])
    return templates.TemplateResponse(
        request,
        "task_form.html",
        {"request": request, "task": task, "status_options": STATUS_OPTIONS, "subtasks": subtasks},
    )


@app.post("/tasks/{task_id}/edit")
def update_task(
    request: Request,
    task_id: str,
    title: str = Form(...),
    task_date: str = Form(...),
    task_time: str = Form(""),
    status: str = Form("не начато"),
    notes: str = Form(""),
    new_subtasks: str = Form(""),
) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    client.table("tasks").update(
        {
            "title": title,
            "task_date": parse_date(task_date, date.today()).isoformat(),
            "task_time": task_time or None,
            "status": status,
            "notes": notes or None,
        }
    ).eq("id", task_id).eq("user_id", user["id"]).execute()
    for line in [item.strip() for item in new_subtasks.splitlines() if item.strip()]:
        client.table("subtasks").insert(
            {"task_id": task_id, "user_id": user["id"], "title": line}
        ).execute()
    return redirect_to("/tasks")


@app.post("/tasks/{task_id}/status")
def update_task_status(request: Request, task_id: str, status: str = Form(...)) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is not None and user is not None:
        client.table("tasks").update({"status": status}).eq("id", task_id).eq("user_id", user["id"]).execute()
    return redirect_to("/tasks")


@app.post("/tasks/{task_id}/delete")
def delete_task(request: Request, task_id: str) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is not None and user is not None:
        client.table("subtasks").delete().eq("task_id", task_id).eq("user_id", user["id"]).execute()
        client.table("tasks").delete().eq("id", task_id).eq("user_id", user["id"]).execute()
    return redirect_to("/tasks")


@app.post("/subtasks/{subtask_id}/toggle")
def toggle_subtask(request: Request, subtask_id: str) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is not None and user is not None:
        response = client.table("subtasks").select("id,completed").eq("id", subtask_id).eq("user_id", user["id"]).limit(1).execute()
        if response.data:
            row = response.data[0]
            client.table("subtasks").update({"completed": not row["completed"]}).eq("id", subtask_id).eq("user_id", user["id"]).execute()
    return redirect_to("/tasks")


@app.post("/subtasks/{subtask_id}/delete")
def delete_subtask(request: Request, subtask_id: str) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is not None and user is not None:
        client.table("subtasks").delete().eq("id", subtask_id).eq("user_id", user["id"]).execute()
    return redirect_to("/tasks")


@app.get("/goals")
def goals_page(request: Request):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    goals = fetch_goals(request)
    steps = fetch_goal_steps(request, [goal.id for goal in goals]) if goals else []
    steps_by_goal: dict[str, list[SimpleNamespace]] = {}
    for step in steps:
        steps_by_goal.setdefault(step.goal_id, []).append(step)

    progress_by_goal: dict[int, int] = {}
    for goal in goals:
        goal_steps = steps_by_goal.get(goal.id, [])
        if not goal_steps:
            progress_by_goal[goal.id] = 100 if goal.completed else 0
            continue
        completed = sum(1 for step in goal_steps if step.completed)
        progress_by_goal[goal.id] = round((completed / len(goal_steps)) * 100)

    return templates.TemplateResponse(
        request,
        "goals.html",
        {
            "request": request,
            "goals": goals,
            "steps_by_goal": steps_by_goal,
            "progress_by_goal": progress_by_goal,
        },
    )


@app.get("/goals/new")
def goal_new_page(request: Request):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    return templates.TemplateResponse(
        request,
        "goal_form.html",
        {
            "request": request,
            "goal": None,
            "goal_types": GOAL_TYPES,
            "goal_categories": GOAL_CATEGORIES,
            "steps": [],
            "default_date": date.today().isoformat(),
        },
    )


@app.post("/goals")
def create_goal(
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    goal_type: str = Form(...),
    due_date: str = Form(""),
    notes: str = Form(""),
    step_titles: str = Form(""),
) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    response = client.table("goals").insert(
        {
            "user_id": user["id"],
            "title": title,
            "category": category,
            "goal_type": goal_type,
            "due_date": parse_date(due_date).isoformat() if parse_date(due_date) else None,
            "notes": notes or None,
        }
    ).execute()
    goal_id = response.data[0]["id"]
    for line in [item.strip() for item in step_titles.splitlines() if item.strip()]:
        client.table("goal_steps").insert(
            {"goal_id": goal_id, "user_id": user["id"], "title": line}
        ).execute()
    return redirect_to("/goals")


@app.get("/goals/{goal_id}/edit")
def goal_edit_page(request: Request, goal_id: str):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    response = client.table("goals").select("*").eq("id", goal_id).eq("user_id", user["id"]).limit(1).execute()
    if not response.data:
        raise HTTPException(status_code=404)
    goal = goal_object_from_row(response.data[0])
    steps = fetch_goal_steps(request, [goal_id])
    return templates.TemplateResponse(
        request,
        "goal_form.html",
        {
            "request": request,
            "goal": goal,
            "goal_types": GOAL_TYPES,
            "goal_categories": GOAL_CATEGORIES,
            "steps": steps,
        },
    )


@app.post("/goals/{goal_id}/edit")
def update_goal(
    request: Request,
    goal_id: str,
    title: str = Form(...),
    category: str = Form(...),
    goal_type: str = Form(...),
    due_date: str = Form(""),
    notes: str = Form(""),
    new_steps: str = Form(""),
) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    client.table("goals").update(
        {
            "title": title,
            "category": category,
            "goal_type": goal_type,
            "due_date": parse_date(due_date).isoformat() if parse_date(due_date) else None,
            "notes": notes or None,
        }
    ).eq("id", goal_id).eq("user_id", user["id"]).execute()
    for line in [item.strip() for item in new_steps.splitlines() if item.strip()]:
        client.table("goal_steps").insert(
            {"goal_id": goal_id, "user_id": user["id"], "title": line}
        ).execute()
    return redirect_to("/goals")


@app.post("/goals/{goal_id}/toggle")
def toggle_goal(request: Request, goal_id: str) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is not None and user is not None:
        response = client.table("goals").select("id,completed").eq("id", goal_id).eq("user_id", user["id"]).limit(1).execute()
        if response.data:
            row = response.data[0]
            client.table("goals").update({"completed": not row["completed"]}).eq("id", goal_id).eq("user_id", user["id"]).execute()
    return redirect_to("/goals")


@app.post("/goals/{goal_id}/delete")
def delete_goal(request: Request, goal_id: str) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is not None and user is not None:
        client.table("goal_steps").delete().eq("goal_id", goal_id).eq("user_id", user["id"]).execute()
        client.table("goals").delete().eq("id", goal_id).eq("user_id", user["id"]).execute()
    return redirect_to("/goals")


@app.post("/goal-steps/{step_id}/toggle")
def toggle_goal_step(request: Request, step_id: str) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is not None and user is not None:
        response = client.table("goal_steps").select("id,completed").eq("id", step_id).eq("user_id", user["id"]).limit(1).execute()
        if response.data:
            row = response.data[0]
            client.table("goal_steps").update({"completed": not row["completed"]}).eq("id", step_id).eq("user_id", user["id"]).execute()
    return redirect_to("/goals")


@app.post("/goal-steps/{step_id}/delete")
def delete_goal_step(request: Request, step_id: str) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is not None and user is not None:
        client.table("goal_steps").delete().eq("id", step_id).eq("user_id", user["id"]).execute()
    return redirect_to("/goals")


@app.get("/habits")
def habits_page(request: Request):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    today = date.today()
    habits = fetch_habits(request)
    logs = fetch_habit_logs(request, [habit.id for habit in habits]) if habits else []
    _, stats = habit_stats_from_logs(habits, logs)
    today_log_map: dict[str, SimpleNamespace] = {}
    for log in logs:
        if log.log_date == today:
            today_log_map[log.habit_id] = log

    return templates.TemplateResponse(
        request,
        "habits.html",
        {
            "request": request,
            "habits": habits,
            "today_log_map": today_log_map,
            "stats": stats,
            "today": today,
            "frequency_labels": HABIT_FREQUENCY_LABELS,
        },
    )


@app.get("/habits/new")
def habit_new_page(request: Request):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    return templates.TemplateResponse(
        request,
        "habit_form.html",
        {
            "request": request,
            "habit": None,
            "frequencies": HABIT_FREQUENCIES,
            "frequency_labels": HABIT_FREQUENCY_LABELS,
        },
    )


@app.post("/habits")
def create_habit(
    request: Request,
    title: str = Form(...),
    habit_type: str = Form(...),
    frequency: str = Form(...),
    schedule_details: str = Form(""),
    target_value: str = Form(""),
    unit: str = Form(""),
) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    client.table("habits").insert(
        {
            "user_id": user["id"],
            "title": title,
            "habit_type": habit_type,
            "frequency": frequency,
            "schedule_details": schedule_details or None,
            "target_value": parse_float(target_value),
            "unit": unit or None,
        }
    ).execute()
    return redirect_to("/habits")


@app.get("/habits/{habit_id}/edit")
def habit_edit_page(request: Request, habit_id: str):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    response = client.table("habits").select("*").eq("id", habit_id).eq("user_id", user["id"]).limit(1).execute()
    if not response.data:
        raise HTTPException(status_code=404)
    habit = habit_object_from_row(response.data[0])
    return templates.TemplateResponse(
        request,
        "habit_form.html",
        {
            "request": request,
            "habit": habit,
            "frequencies": HABIT_FREQUENCIES,
            "frequency_labels": HABIT_FREQUENCY_LABELS,
        },
    )


@app.post("/habits/{habit_id}/edit")
def update_habit(
    request: Request,
    habit_id: str,
    title: str = Form(...),
    habit_type: str = Form(...),
    frequency: str = Form(...),
    schedule_details: str = Form(""),
    target_value: str = Form(""),
    unit: str = Form(""),
) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    client.table("habits").update(
        {
            "title": title,
            "habit_type": habit_type,
            "frequency": frequency,
            "schedule_details": schedule_details or None,
            "target_value": parse_float(target_value),
            "unit": unit or None,
        }
    ).eq("id", habit_id).eq("user_id", user["id"]).execute()
    return redirect_to("/habits")


@app.post("/habits/{habit_id}/log")
def log_habit(
    request: Request,
    habit_id: str,
    log_date: str = Form(...),
    completed: str = Form("false"),
    numeric_value: str = Form(""),
) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    current_date = parse_date(log_date, date.today())
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    response = (
        client.table("habit_logs")
        .select("*")
        .eq("habit_id", habit_id)
        .eq("user_id", user["id"])
        .eq("log_date", current_date.isoformat())
        .limit(1)
        .execute()
    )
    payload = {
        "habit_id": habit_id,
        "user_id": user["id"],
        "log_date": current_date.isoformat(),
        "completed": completed == "true",
        "numeric_value": parse_float(numeric_value),
    }
    if response.data:
        client.table("habit_logs").update(payload).eq("id", response.data[0]["id"]).eq("user_id", user["id"]).execute()
    else:
        client.table("habit_logs").insert(payload).execute()
    return redirect_to("/habits")


@app.post("/habits/{habit_id}/delete")
def delete_habit(request: Request, habit_id: str) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is not None and user is not None:
        client.table("habit_logs").delete().eq("habit_id", habit_id).eq("user_id", user["id"]).execute()
        client.table("habits").delete().eq("id", habit_id).eq("user_id", user["id"]).execute()
    return redirect_to("/habits")


@app.get("/measurements")
def measurements_page(request: Request):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    entries = fetch_measurements(request)
    latest = entries[0] if entries else None
    previous = entries[1] if len(entries) > 1 else None
    earliest = entries[-1] if entries else None
    return templates.TemplateResponse(
        request,
        "measurements.html",
        {
            "request": request,
            "entries": entries,
            "latest": latest,
            "previous": previous,
            "earliest": earliest,
        },
    )


@app.get("/measurements/new")
def measurement_new_page(request: Request):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    return templates.TemplateResponse(
        request,
        "measurement_form.html",
        {"request": request, "entry": None, "default_date": date.today().isoformat()},
    )


@app.post("/measurements")
def create_measurement(
    request: Request,
    entry_date: str = Form(...),
    weight: str = Form(""),
    waist: str = Form(""),
    chest: str = Form(""),
    hips: str = Form(""),
    glutes: str = Form(""),
    legs: str = Form(""),
) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    client.table("measurement_entries").insert(
        {
            "user_id": user["id"],
            "entry_date": parse_date(entry_date, date.today()).isoformat(),
            "weight": parse_float(weight),
            "waist": parse_float(waist),
            "chest": parse_float(chest),
            "hips": parse_float(hips),
            "glutes": parse_float(glutes),
            "legs": parse_float(legs),
        }
    ).execute()
    return redirect_to("/measurements")


@app.get("/measurements/{entry_id}/edit")
def measurement_edit_page(request: Request, entry_id: str):
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    response = (
        client.table("measurement_entries")
        .select("*")
        .eq("id", entry_id)
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404)
    entry = measurement_object_from_row(response.data[0])
    return templates.TemplateResponse(
        request, "measurement_form.html", {"request": request, "entry": entry}
    )


@app.post("/measurements/{entry_id}/edit")
def update_measurement(
    request: Request,
    entry_id: str,
    entry_date: str = Form(...),
    weight: str = Form(""),
    waist: str = Form(""),
    chest: str = Form(""),
    hips: str = Form(""),
    glutes: str = Form(""),
    legs: str = Form(""),
) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is None or user is None:
        return redirect_to("/login")
    client.table("measurement_entries").update(
        {
            "entry_date": parse_date(entry_date, date.today()).isoformat(),
            "weight": parse_float(weight),
            "waist": parse_float(waist),
            "chest": parse_float(chest),
            "hips": parse_float(hips),
            "glutes": parse_float(glutes),
            "legs": parse_float(legs),
        }
    ).eq("id", entry_id).eq("user_id", user["id"]).execute()
    return redirect_to("/measurements")


@app.post("/measurements/{entry_id}/delete")
def delete_measurement(request: Request, entry_id: str) -> RedirectResponse:
    auth_redirect = require_auth(request)
    if auth_redirect:
        return auth_redirect
    client = get_authenticated_supabase(request)
    user = get_current_user(request)
    if client is not None and user is not None:
        client.table("measurement_entries").delete().eq("id", entry_id).eq("user_id", user["id"]).execute()
    return redirect_to("/measurements")
