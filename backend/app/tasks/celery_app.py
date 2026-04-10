from celery import Celery
from celery.schedules import crontab
from ..config import REDIS_URL

celery = Celery(
    "leadgen",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.tasks.agent_tasks",
        "app.tasks.followup_tasks",
        "app.tasks.warmup_tasks",
        "app.tasks.wa_tasks",
        "app.tasks.report_tasks",
        "app.tasks.health_tasks",
        "app.tasks.opro_tasks",
        "app.tasks.demo_tasks",
        "app.tasks.webhook_tasks",
        "app.tasks.autonomous_tasks",
        "app.tasks.rag_tasks",
        "app.tasks.ab_testing_tasks",
        "app.tasks.multi_agent_tasks",
    ]
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_always_eager=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "daily-agent-run": {
            "task": "app.tasks.agent_tasks.run_all_agents",
            "schedule": crontab(hour=9, minute=0),          # 9 AM IST
        },
        "weekly-report": {
            "task": "app.tasks.report_tasks.send_weekly_reports",
            "schedule": crontab(hour=3, minute=30, day_of_week=1),  # Monday 9 AM IST
        },
        "warmup-check": {
            "task": "app.tasks.warmup_tasks.check_all_warmups",
            "schedule": crontab(minute=0),                  # every hour
        },
        "wa-health-check": {
            "task": "app.tasks.wa_tasks.check_all_wa_health",
            "schedule": crontab(minute=0, hour="*/6"),       # every 6 hours
        },
        "client-health-check": {
            "task": "app.tasks.health_tasks.check_all_client_health",
            "schedule": crontab(hour=2, minute=30),          # 8 AM IST
        },
        "demo-cleanup": {
            "task": "app.tasks.demo_tasks.cleanup_expired_demos",
            "schedule": crontab(hour=1, minute=0),           # 1 AM UTC daily
        },
        "opro-weekly-optimize": {
            "task": "app.tasks.opro_tasks.run_opro_for_all_clients",
            "schedule": crontab(hour=20, minute=30, day_of_week=1),  # Monday 2 AM IST (UTC+5:30)
        },
        "autonomous-loop": {
            "task": "app.tasks.autonomous_tasks.run_autonomous_loop_all_clients",
            "schedule": crontab(hour=0, minute=30),  # 6 AM IST (UTC+5:30)
        },
        "rag-daily-sync": {
            "task": "app.tasks.rag_tasks.sync_all_client_messages",
            "schedule": crontab(hour=1, minute=30),  # 1:30 AM IST daily
        },
        "ab-test-weekly-start": {
            "task": "app.tasks.ab_testing_tasks.start_weekly_ab_tests",
            "schedule": crontab(hour=3, minute=0, day_of_week=1),  # Monday 3am IST
        },
        "ab-test-significance-check": {
            "task": "app.tasks.ab_testing_tasks.check_all_running_tests",
            "schedule": crontab(hour="*/6", minute=30),  # every 6 hours
        },
    }
)
