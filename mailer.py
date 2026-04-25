import smtplib
import os
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GMAIL_ADDRESS = os.getenv("SMTP_USER")
GMAIL_APP_PASSWORD = os.getenv("SMTP_PASSWORD")


def send_content_email(to_email: str, topic: str, content: dict):

    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        logger.error("[Mailer] ❌ SMTP_USER or SMTP_PASSWORD is not set in environment!")
        return

    logger.info(f"[Mailer] Preparing email to {to_email} | from {GMAIL_ADDRESS}")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚀 Daily Content: {topic}"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_email

    hashtags_html = ""
    if content.get("instagram_hashtags"):
        tags = content["instagram_hashtags"]
        if isinstance(tags, list):
            tags = " ".join(tags)
        hashtags_html = f'<div class="hashtags">{tags}</div>'

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8">
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f8fafc; margin: 0; padding: 0; }}
        .wrapper {{ max-width: 640px; margin: 30px auto; background: white; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
        .header {{ background: linear-gradient(135deg, #4f46e5, #6366f1); padding: 2rem; text-align: center; color: white; }}
        .header h1 {{ margin: 0; font-size: 1.5rem; font-weight: 700; }}
        .header p {{ margin: 0.5rem 0 0; opacity: 0.85; font-size: 0.9rem; }}
        .body {{ padding: 1.5rem; }}
        .section {{ background: #f8fafc; border-radius: 12px; padding: 1.25rem; margin-bottom: 1.25rem; border-left: 4px solid #4f46e5; }}
        .section-title {{ font-weight: 700; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; color: #4f46e5; margin-bottom: 0.75rem; }}
        .section-body {{ font-size: 0.95rem; line-height: 1.7; color: #1e293b; white-space: pre-wrap; }}
        .section.instagram {{ border-left-color: #e1306c; }}
        .section.instagram .section-title {{ color: #e1306c; }}
        .section.linkedin {{ border-left-color: #0077b5; }}
        .section.linkedin .section-title {{ color: #0077b5; }}
        .section.article {{ border-left-color: #2ecc71; }}
        .section.article .section-title {{ color: #16a34a; }}
        .section.announcement {{ border-left-color: #9b59b6; }}
        .section.announcement .section-title {{ color: #9b59b6; }}
        .hashtags {{ background: #eff6ff; border: 1px solid #dbeafe; border-radius: 8px; padding: 0.75rem; margin-top: 0.75rem; font-family: monospace; font-size: 0.85rem; color: #1d4ed8; }}
        .footer {{ text-align: center; padding: 1.25rem; font-size: 0.8rem; color: #94a3b8; border-top: 1px solid #e2e8f0; }}
    </style>
    </head>
    <body>
    <div class="wrapper">
        <div class="header">
            <h1>🚀 Social Engine Pro</h1>
            <p>Your daily content for: <strong>{topic}</strong></p>
        </div>
        <div class="body">
            <div class="section instagram">
                <div class="section-title">📸 Instagram Caption</div>
                <div class="section-body">{content.get('instagram_caption', 'N/A')}</div>
                {hashtags_html}
            </div>
            <div class="section linkedin">
                <div class="section-title">💼 LinkedIn Post</div>
                <div class="section-body">{content.get('linkedin_post', 'N/A')}</div>
            </div>
            <div class="section article">
                <div class="section-title">📄 LinkedIn Article</div>
                <div class="section-body">{content.get('linkedin_article', 'N/A')}</div>
            </div>
            <div class="section announcement">
                <div class="section-title">📣 Announcement</div>
                <div class="section-body">{content.get('announcement', 'N/A')}</div>
            </div>
        </div>
        <div class="footer">Sent automatically by Social Engine Pro · Manage in Automation settings</div>
    </div>
    </body></html>
    """

    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, to_email, msg.as_string())
            logger.info(f"[Mailer] ✅ Email successfully sent to {to_email}")

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "[Mailer] ❌ Authentication failed — "
            "check that SMTP_PASSWORD is a valid Gmail App Password, not your regular password"
        )
    except smtplib.SMTPRecipientsRefused:
        logger.error(f"[Mailer] ❌ Recipient refused: {to_email} — check the email address is valid")
    except smtplib.SMTPSenderRefused:
        logger.error(f"[Mailer] ❌ Sender refused: {GMAIL_ADDRESS} — check SMTP_USER is correct")
    except smtplib.SMTPException as e:
        logger.error(f"[Mailer] ❌ SMTP error: {e}")
    except Exception as e:
        logger.error(f"[Mailer] ❌ Unexpected error while sending email: {e}", exc_info=True)