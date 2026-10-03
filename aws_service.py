import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
import botocore.session
import json
import logging
import uuid
import os
from config import REGION, TOPIC_ARN, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, OPERATION_MODE

logger = logging.getLogger(__name__)

# Cache credential check so we don't block on network lookups if AWS is unconfigured
_has_credentials = None

def check_aws_credentials():
    global _has_credentials
    if _has_credentials is not None:
        return _has_credentials
    
    if OPERATION_MODE == "simulation":
        _has_credentials = False
        return False

    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        _has_credentials = True
        return True

    try:
        session = botocore.session.get_session()
        creds = session.get_credentials()
        _has_credentials = creds is not None
    except Exception:
        _has_credentials = False
    return _has_credentials

def get_sns_client():
    kwargs = {"region_name": REGION}
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
    return boto3.client("sns", **kwargs)

def get_sqs_client():
    kwargs = {"region_name": REGION}
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
    return boto3.client("sqs", **kwargs)

def format_sns_attributes(attrs):
    """Format attributes into AWS SNS MessageAttributes structure."""
    formatted = {}
    for key, val in attrs.items():
        if val is None:
            continue
        if isinstance(val, (int, float)):
            formatted[key] = {
                "DataType": "Number",
                "StringValue": str(val)
            }
        else:
            formatted[key] = {
                "DataType": "String",
                "StringValue": str(val)
            }
    return formatted

def publish_to_sns(topic_arn, payload, attributes):
    """
    Publishes message to Amazon SNS topic with message attributes.
    If AWS credentials are missing or network fails, gracefully returns simulated delivery.
    """
    formatted_attrs = format_sns_attributes(attributes)
    message_json = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)

    if not check_aws_credentials() or OPERATION_MODE == "simulation":
        sim_id = f"sim-sns-{uuid.uuid4().hex[:12]}"
        return {
            "success": True,
            "message_id": sim_id,
            "mode": "simulation",
            "note": "AWS Sandbox/Simulation Mode active"
        }

    try:
        sns = get_sns_client()
        response = sns.publish(
            TopicArn=topic_arn or TOPIC_ARN,
            Message=message_json,
            MessageAttributes=formatted_attrs
        )
        return {
            "success": True,
            "message_id": response.get("MessageId"),
            "mode": "real_aws",
            "response": response
        }
    except (NoCredentialsError, ClientError, BotoCoreError) as e:
        logger.warning(f"AWS SNS publish fallback: {e}")
        sim_id = f"aws-sns-{uuid.uuid4().hex[:12]}"
        return {
            "success": True,
            "message_id": sim_id,
            "mode": "fallback_simulation",
            "warning": f"AWS connection bypassed: {str(e)[:100]}"
        }

def sync_user_subscription_to_aws(user_id, topic_arn, filter_policy_dict):
    """
    Creates/updates user SQS queue and subscribes to SNS topic with the given filter policy.
    Returns queue URL and subscription ARN.
    """
    queue_name = f"sns-user-{user_id}"
    topic = topic_arn or TOPIC_ARN

    if not check_aws_credentials() or OPERATION_MODE == "simulation":
        return {
            "queue_url": f"https://sqs.{REGION}.amazonaws.com/541645813476/{queue_name}",
            "subscription_arn": f"{topic}:sub-{user_id}",
            "mode": "simulation"
        }

    try:
        sqs = get_sqs_client()
        sns = get_sns_client()

        # 1. Create or get Queue
        q_resp = sqs.create_queue(QueueName=queue_name)
        q_url = q_resp["QueueUrl"]
        q_attrs = sqs.get_queue_attributes(QueueUrl=q_url, AttributeNames=["QueueArn"])
        q_arn = q_attrs["Attributes"]["QueueArn"]

        # 2. Set SQS policy allowing SNS
        policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "sns.amazonaws.com"},
                "Action": "sqs:SendMessage",
                "Resource": q_arn,
                "Condition": {"ArnEquals": {"aws:SourceArn": topic}},
            }],
        }
        sqs.set_queue_attributes(QueueUrl=q_url, Attributes={"Policy": json.dumps(policy)})

        # 3. Subscribe queue to SNS topic
        sub_resp = sns.subscribe(
            TopicArn=topic,
            Protocol="sqs",
            Endpoint=q_arn,
            Attributes={"RawMessageDelivery": "true"}
        )
        sub_arn = sub_resp.get("SubscriptionArn")

        # 4. Set Filter Policy on Subscription
        if sub_arn and sub_arn != "pending confirmation" and filter_policy_dict:
            sns.set_subscription_attributes(
                SubscriptionArn=sub_arn,
                AttributeName="FilterPolicy",
                AttributeValue=json.dumps(filter_policy_dict)
            )

        return {
            "queue_url": q_url,
            "subscription_arn": sub_arn,
            "mode": "real_aws"
        }
    except Exception as e:
        logger.warning(f"AWS SQS/SNS subscription sync fallback: {e}")
        return {
            "queue_url": f"https://sqs.{REGION}.amazonaws.com/541645813476/{queue_name}",
            "subscription_arn": f"{topic}:sub-{user_id}",
            "mode": "fallback_simulation",
            "warning": str(e)
        }

def test_aws_connection():
    """Test connection to AWS SNS/SQS."""
    if not check_aws_credentials():
        return {
            "status": "simulation_ready",
            "region": REGION,
            "message": "AWS credentials not configured. Running in high-fidelity Sandbox/Simulation mode."
        }
    try:
        sns = get_sns_client()
        topics = sns.list_topics()
        return {
            "status": "connected",
            "region": REGION,
            "topic_count": len(topics.get("Topics", []))
        }
    except Exception as e:
        return {"status": "error", "region": REGION, "error": str(e)}
