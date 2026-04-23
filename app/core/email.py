import logging
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from sib_api_v3_sdk.api.transactional_emails_api import TransactionalEmailsApi
from sib_api_v3_sdk.models.send_smtp_email import SendSmtpEmail

from app.core.config import settings

# Setup standard logging
logger = logging.getLogger(__name__)

def send_email(receiver_email: str, subject: str, html_content: str, sender_name: str = "BullShit") -> bool:
    """
    Sends a generic transactional email using Brevo API.
    
    Args:
        receiver_email (str): The recipient's email address.
        subject (str): The subject of the email.
        html_content (str): The raw HTML content of the email body.
        sender_name (str, optional): Name of the sender. Defaults to "BullShit".
    
    Returns:
        bool: True if email sent successfully, False otherwise.
    """
    try:
        api_key = settings.BREVO_API_KEY
        sender_email = settings.BREVO_API_EMAIL
        
        if not api_key or not sender_email:
            logger.error("Brevo API credentials not configured in environment variables.")
            return False
        
        # Configure API key authorization
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = api_key
        
        # Create an instance of the API class
        api_instance = TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))
        
        email = SendSmtpEmail(
            sender={"email": sender_email, "name": sender_name},
            to=[{"email": receiver_email}],
            subject=subject,
            html_content=html_content
        )
        
        # Send the transactional email
        response = api_instance.send_transac_email(email)
        logger.info(f"Email sent successfully to {receiver_email}. Response: {response}")
        return True
        
    except ApiException as e:
        logger.error(f"Brevo API error sending email to {receiver_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending email to {receiver_email}: {e}")
        return False