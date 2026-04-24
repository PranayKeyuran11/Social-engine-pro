from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import sqlite3
import pytz
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")


def get_db():
    conn = sqlite3.connect("users.db")
    conn.row_factory = sqlite3.Row
    return conn


def get_all_active_automations():
    with get_db() as conn:
        return conn.execute("SELECT * FROM automations WHERE is_active = 1").fetchall()


def run_automation_for_user(automation_id: int):
    from graph.orchestrator import build_graph
    from mailer import send_content_email

    with get_db() as conn:
        auto = conn.execute("SELECT * FROM automations WHERE id = ?", (automation_id,)).fetchone()

    if not auto or not auto["is_active"]:
        return

    # ── Pick today's topic from the rotation list ──
    raw_topics = auto["topics"] or ""
    topics = [t.strip() for t in raw_topics.split("||") if t.strip()]

    if not topics:
        logger.error(f"[Scheduler] Automation #{automation_id} has no topics configured.")
        return

    current_index = auto["current_index"] or 0
    topic = topics[current_index % len(topics)]
    next_index = (current_index + 1) % len(topics)

    context = auto["context"] or ""
    to_email = auto["email"]

    logger.info(f"[Scheduler] Automation #{automation_id} → topic [{current_index+1}/{len(topics)}]: '{topic}' → {to_email}")

    try:
        graph = build_graph()
        result = graph.invoke({
            "topic": topic, "context": context,
            "instagram_caption": None, "instagram_hashtags": None,
            "linkedin_post": None, "linkedin_article": None, "announcement": None,
        })
        send_content_email(to_email, topic, dict(result))
        logger.info(f"[Scheduler] ✅ Email sent to {to_email}")

        # Advance index and update last_sent
        with get_db() as conn:
            conn.execute(
                "UPDATE automations SET last_sent = CURRENT_TIMESTAMP, current_index = ? WHERE id = ?",
                (next_index, automation_id)
            )
            conn.commit()

    except Exception as e:
        logger.error(f"[Scheduler] ❌ Automation #{automation_id} failed: {e}")


def schedule_automation(automation_id: int, hour: int, minute: int, timezone: str = "Asia/Kolkata"):
    job_id = f"auto_{automation_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    try:
        tz = pytz.timezone(timezone)
    except Exception:
        tz = pytz.timezone("Asia/Kolkata")

    scheduler.add_job(
        run_automation_for_user,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
        args=[automation_id],
        id=job_id,
        replace_existing=True,
    )
    logger.info(f"[Scheduler] Scheduled job {job_id} at {hour:02d}:{minute:02d} ({timezone})")


def unschedule_automation(automation_id: int):
    job_id = f"auto_{automation_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"[Scheduler] Removed job {job_id}")


def reload_all_automations():
    for auto in get_all_active_automations():
        try:
            h, m = map(int, auto["send_time"].split(":"))
            schedule_automation(auto["id"], h, m, auto["timezone"])
        except Exception as e:
            logger.error(f"[Scheduler] Failed to reload automation #{auto['id']}: {e}")


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        reload_all_automations()
        logger.info("[Scheduler] Started.")