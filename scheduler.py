import os
import pytz
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
scheduler = BackgroundScheduler(timezone=IST)

DATABASE_URL = os.environ.get("DATABASE_URL")


# ─────────────────────────────────────────────
#  DB HELPER
# ─────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


# ─────────────────────────────────────────────
#  CORE: Run a single automation
# ─────────────────────────────────────────────

def run_automation_for_user(automation_id: int):
    from graph.orchestrator import build_graph
    from mailer import send_content_email

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM automations WHERE id = %s", (automation_id,))
            auto = cur.fetchone()
    finally:
        conn.close()

    if not auto or not auto["is_active"]:
        logger.warning(f"[Scheduler] Automation #{automation_id} is inactive or missing — skipping.")
        return

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

    # Stamp last_sent BEFORE LLM call so next heartbeat tick doesn't re-trigger
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE automations SET last_sent = %s, current_index = %s WHERE id = %s",
                (now_ist, next_index, automation_id),
            )
        conn.commit()
    finally:
        conn.close()

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

    except Exception as e:
        logger.error(f"[Scheduler] ❌ Automation #{automation_id} failed: {e}", exc_info=True)
        # Roll back index so same topic retries tomorrow
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE automations SET current_index = %s WHERE id = %s",
                    (current_index, automation_id),
                )
            conn.commit()
        finally:
            conn.close()


# ─────────────────────────────────────────────
#  HEARTBEAT: Fires every minute, polls DB
# ─────────────────────────────────────────────

def check_and_run_due_automations():
    now = datetime.now(IST)
    current_time = f"{now.hour:02d}:{now.minute:02d}"
    current_date = now.strftime("%Y-%m-%d")

    logger.info(f"[Heartbeat] Tick at {current_time} IST ({current_date})")

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM automations
                WHERE is_active = TRUE
                  AND send_time = %s
                  AND (
                      last_sent IS NULL
                      OR DATE(last_sent) < %s::date
                  )
            """, (current_time, current_date))
            due = cur.fetchall()
    except Exception as e:
        logger.error(f"[Heartbeat] DB query failed: {e}", exc_info=True)
        conn.close()
        return
    finally:
        conn.close()

    if not due:
        return

    logger.info(f"[Heartbeat] {len(due)} automation(s) due at {current_time}")
    for auto in due:
        try:
            run_automation_for_user(auto["id"])
        except Exception as e:
            logger.error(f"[Heartbeat] Failed to run automation #{auto['id']}: {e}", exc_info=True)


# ─────────────────────────────────────────────
#  PUBLIC API — kept for route compatibility
# ─────────────────────────────────────────────

def schedule_automation(automation_id: int, hour: int, minute: int, timezone: str = "Asia/Kolkata"):
    logger.info(
        f"[Scheduler] Automation #{automation_id} registered for "
        f"{hour:02d}:{minute:02d} ({timezone}) — heartbeat will pick it up."
    )


def unschedule_automation(automation_id: int):
    logger.info(
        f"[Scheduler] Automation #{automation_id} marked inactive — "
        f"heartbeat will skip it from next tick."
    )


# ─────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────

def start_scheduler():
    if scheduler.running:
        logger.info("[Scheduler] Already running — skipping start.")
        return

    scheduler.start()

    scheduler.add_job(
        check_and_run_due_automations,
        trigger=CronTrigger(minute="*", timezone=IST),
        id="heartbeat",
        replace_existing=True,
    )

    logger.info("[Scheduler] ✅ Started. Heartbeat polling every minute (IST).")