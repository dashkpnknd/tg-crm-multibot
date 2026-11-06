"""Environment-only credentials for the CRM service."""

import os

BOT_TOKEN = os.environ["CRM_BOT_TOKEN"]
BOT_API_HASH = os.environ["CRM_BOT_API_HASH"]
ACCOUNT_API_HASH = os.environ["CRM_ACCOUNT_API_HASH"]
LOG_CHAT_ID = int(os.environ["CRM_LOG_CHAT_ID"])
