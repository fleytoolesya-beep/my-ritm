FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY planner_app/requirements.txt /app/planner_app/requirements.txt
RUN pip install --no-cache-dir -r /app/planner_app/requirements.txt

COPY planner_app /app/planner_app

WORKDIR /app/planner_app

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
