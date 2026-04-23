import logging
import re
from twilio.rest import Client
from app.core.config import settings

logger = logging.getLogger(__name__)

def send_sms(message_text: str, recipient: str) -> str:
    """
    Sends SMS via Twilio.

    Args:
        message_text (str): The SMS text content.
        recipient (str): The recipient's phone number.

    Returns:
        str: Message SID upon successful send.
    """

    # Normalize phone number format (assuming India +91 default as per user code)
    recipient = re.sub(r'\D', '', recipient)
    if not recipient.startswith("91"):
        recipient = "91" + recipient
    recipient = "+" + recipient

    logger.info(f"Attempting to send SMS to {recipient}: {message_text[:50]}...")

    # Check if Twilio credentials are available
    try:
        tw_sid = settings.TWILIO_ACCOUNT_SID
        tw_auth = settings.TWILIO_AUTH_TOKEN
        tw_from = settings.TWILIO_FROM_NUMBER
        twilio_available = bool(tw_sid and tw_auth and tw_from)
    except Exception:
        twilio_available = False

    if not twilio_available:
        logger.error("Twilio credentials are not fully configured in the environment.")
        raise Exception("Twilio SMS service is not configured")

    try:
        # Use Twilio
        client = Client(tw_sid, tw_auth)
        msg = client.messages.create(
            body=message_text,
            from_=tw_from,
            to=recipient
        )
        logger.info(f"SMS sent via Twilio to {recipient}: {msg.sid}")
        return msg.sid

    except Exception as e:
        logger.exception(f"Twilio SMS failed to {recipient}: {e}")
        raise Exception(f"SMS sending failed via Twilio: {type(e).__name__}: {str(e)}")
