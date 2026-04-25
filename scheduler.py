import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import sqlite3
import pytz
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FIX 1 — Use IST as the scheduler base timezone instead of UTC
IST = pytz.timezone("Asia/Kolkata")
scheduler = BackgroundScheduler(timezone=IST)


DB_PATH = os.environ.get("DB_PATH", "/data/users.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
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
        logger.warning(f"[Scheduler] Automation #{automation_id} is inactive or not found — skipping.")
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

    logger.info(
        f"[Scheduler] Automation #{automation_id} → "
        f"topic [{current_index + 1}/{len(topics)}]: '{topic}' → {to_email}"
    )

    try:
        graph = build_graph()
        result = graph.invoke({
            "topic": topic,
            "context": context,
            "instagram_caption": None,
            "instagram_hashtags": None,
            "linkedin_post": None,
            "linkedin_article": None,
            "announcement": None,
        })
        send_content_email(to_email, topic, dict(result))
        logger.info(f"[Scheduler] ✅ Email sent to {to_email} for automation #{automation_id}")

        # Advance topic index and update last_sent
        with get_db() as conn:
            conn.execute(
                "UPDATE automations SET last_sent = CURRENT_TIMESTAMP, current_index = ? WHERE id = ?",
                (next_index, automation_id),
            )
            conn.commit()

    except Exception as e:
        logger.error(f"[Scheduler] ❌ Automation #{automation_id} failed: {e}", exc_info=True)


def schedule_automation(automation_id: int, hour: int, minute: int, timezone: str = "Asia/Kolkata"):
    job_id = f"auto_{automation_id}"

    # Remove existing job first so we don't get duplicates on reload
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    # FIX 2 — Safe timezone fallback so NULL from DB never causes a silent UTC default
    try:
        tz = pytz.timezone(timezone) if timezone else IST
    except Exception:
        logger.warning(f"[Scheduler] Invalid timezone '{timezone}' for job {job_id} — defaulting to IST")
        tz = IST

    scheduler.add_job(
        run_automation_for_user,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
        args=[automation_id],
        id=job_id,
        replace_existing=True,
    )
    logger.info(f"[Scheduler] Scheduled job {job_id} at {hour:02d}:{minute:02d} ({tz.zone})")


def unschedule_automation(automation_id: int):
    job_id = f"auto_{automation_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"[Scheduler] Removed job {job_id}")
    else:
        logger.warning(f"[Scheduler] Job {job_id} not found — nothing to remove")


def reload_all_automations():
    """Re-register all active automation jobs from the DB.
    Called on startup so jobs survive Render restarts.
    """
    automations = get_all_active_automations()
    logger.info(f"[Scheduler] Reloading {len(automations)} active automation(s)...")

    for auto in automations:
        try:
            h, m = map(int, auto["send_time"].split(":"))

            # FIX 2 — Never pass NULL timezone to schedule_automation
            tz = auto["timezone"] if auto["timezone"] else "Asia/Kolkata"

            logger.info(
                f"[Scheduler] Reloading #{auto['id']} "
                f"at {h:02d}:{m:02d} tz={tz} → {auto['email']}"
            )
            schedule_automation(auto["id"], h, m, tz)

        except Exception as e:
            logger.error(f"[Scheduler] Failed to reload automation #{auto['id']}: {e}", exc_info=True)


def start_scheduler():
    # FIX 3 — Guard against double-start (important on Render with hot reloads)
    if not scheduler.running:
        scheduler.start()
        reload_all_automations()
        logger.info("[Scheduler] ✅ Started and all jobs loaded.")
    else:
        logger.info("[Scheduler] Already running — skipping start.")