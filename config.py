import os
from dotenv import load_dotenv

# Load .env file if available
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = os.environ.get("SECRET_KEY", "sns-filterhub-dev-secret-key-998877")
DATABASE_PATH = os.environ.get("DATABASE_URL", os.path.join(BASE_DIR, "sns_filterhub.db"))

REGION = os.environ.get("AWS_REGION", "us-east-1")
TOPIC_ARN = os.environ.get(
    "SNS_TOPIC_ARN",
    "arn:aws:sns:us-east-1:541645813476:order-events-topic"
)
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

# Operation mode: "real", "simulation", or "auto" (default: auto tries real, falls back to high-fidelity simulation if AWS is unreachable or keys absent)
OPERATION_MODE = os.environ.get("OPERATION_MODE", "auto")

# Legacy queues preserved for backward-compatible simulator & demo
QUEUES = {
    "high_value": {
        "name": "high-value-orders-queue",
        "url": "https://sqs.us-east-1.amazonaws.com/541645813476/high-value-orders-queue",
    },
    "electronics": {
        "name": "electronics-orders-queue",
        "url": "https://sqs.us-east-1.amazonaws.com/541645813476/electronics-orders-queue",
    },
    "premium": {
        "name": "premium-customers-queue",
        "url": "https://sqs.us-east-1.amazonaws.com/541645813476/premium-customers-queue",
    },
    "all": {
        "name": "all-orders-queue",
        "url": "https://sqs.us-east-1.amazonaws.com/541645813476/all-orders-queue",
    },
}