import logging
import time
from datetime import timedelta

from sqlmodel import Session, col, select

from app.core.db import engine
from app.models import (
    NotificationOutbox,
    NotificationStatus,
    User,
    get_datetime_utc,
)
from app.utils import send_email

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


def process_next_notification() -> bool:
    with Session(engine) as session:
        notification = session.exec(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status.in_(
                    [NotificationStatus.PENDING, NotificationStatus.FAILED]
                ),
                NotificationOutbox.attempts < MAX_ATTEMPTS,
                NotificationOutbox.available_at <= get_datetime_utc(),
            )
            .order_by(col(NotificationOutbox.created_at))
            .with_for_update(skip_locked=True)
            .limit(1)
        ).first()
        if notification is None:
            return False

        notification.status = NotificationStatus.PROCESSING
        notification.attempts += 1
        session.add(notification)
        session.commit()

        try:
            recipient = session.get(User, notification.recipient_id)
            if recipient is None:
                raise RuntimeError("Notification recipient no longer exists")
            title = notification.payload.get("title", "Document")
            send_email(
                email_to=recipient.email,
                subject=f"Review requested: {title}",
                html_content=(
                    f"<p>A document is waiting for your review.</p>"
                    f"<p>Document ID: {notification.payload.get('document_id')}</p>"
                ),
            )
        except Exception as exc:
            notification.status = NotificationStatus.FAILED
            notification.last_error = str(exc)[:1000]
            notification.available_at = get_datetime_utc() + timedelta(
                seconds=min(300, 2**notification.attempts)
            )
            session.add(notification)
            session.commit()
            logger.exception("Notification delivery failed: %s", notification.id)
            return True

        notification.status = NotificationStatus.SENT
        notification.processed_at = get_datetime_utc()
        notification.last_error = None
        session.add(notification)
        session.commit()
        logger.info("Notification delivered: %s", notification.id)
        return True


def run_worker() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("Notification worker started")
    while True:
        try:
            processed = process_next_notification()
        except Exception:
            logger.exception("Notification worker iteration failed; retrying")
            time.sleep(5)
            continue
        if not processed:
            time.sleep(2)


if __name__ == "__main__":
    run_worker()
