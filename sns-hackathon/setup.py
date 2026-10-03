import boto3
import json

REGION = "us-east-1"

sns = boto3.client("sns", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)

# ---------- STEP 1: Create SNS Topic ----------
print("Creating SNS topic...")
topic = sns.create_topic(Name="order-events-topic")
topic_arn = topic["TopicArn"]
print(f"  Topic ARN: {topic_arn}")

# ---------- STEP 2: Create 4 SQS Queues ----------
queue_names = [
    "high-value-orders-queue",
    "electronics-orders-queue",
    "premium-customers-queue",
    "all-orders-queue",
]

queues = {}
for name in queue_names:
    print(f"Creating queue: {name}")
    q = sqs.create_queue(QueueName=name)
    q_url = q["QueueUrl"]
    attrs = sqs.get_queue_attributes(
        QueueUrl=q_url, AttributeNames=["QueueArn"]
    )
    q_arn = attrs["Attributes"]["QueueArn"]
    queues[name] = {"url": q_url, "arn": q_arn}
    print(f"  URL: {q_url}")

# ---------- STEP 3: Allow SNS to send to each queue ----------
print("Setting SQS queue policies...")
for name, q in queues.items():
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "sns.amazonaws.com"},
            "Action": "sqs:SendMessage",
            "Resource": q["arn"],
            "Condition": {"ArnEquals": {"aws:SourceArn": topic_arn}},
        }],
    }
    sqs.set_queue_attributes(
        QueueUrl=q["url"],
        Attributes={"Policy": json.dumps(policy)},
    )

# ---------- STEP 4: Subscribe queues to the topic ----------
print("Subscribing queues to topic...")
subscriptions = {}
for name, q in queues.items():
    sub = sns.subscribe(
        TopicArn=topic_arn,
        Protocol="sqs",
        Endpoint=q["arn"],
        Attributes={"RawMessageDelivery": "true"},
    )
    subscriptions[name] = sub["SubscriptionArn"]
    print(f"  Subscribed: {name}")

# ---------- STEP 5: Apply Filter Policies ----------
print("Applying filter policies...")

sns.set_subscription_attributes(
    SubscriptionArn=subscriptions["high-value-orders-queue"],
    AttributeName="FilterPolicy",
    AttributeValue=json.dumps({"price_usd": [{"numeric": [">", 100]}]}),
)

sns.set_subscription_attributes(
    SubscriptionArn=subscriptions["electronics-orders-queue"],
    AttributeName="FilterPolicy",
    AttributeValue=json.dumps({"category": ["electronics", "computers"]}),
)

sns.set_subscription_attributes(
    SubscriptionArn=subscriptions["premium-customers-queue"],
    AttributeName="FilterPolicy",
    AttributeValue=json.dumps({"customer_tier": ["premium", "gold"]}),
)

# all-orders-queue: no filter = receives everything

print("\n========================================")
print("SETUP COMPLETE!")
print("========================================")
print(f"\nTOPIC_ARN = \"{topic_arn}\"\n")
print("QUEUES = {")
for name, q in queues.items():
    print(f'    "{name}": {{')
    print(f'        "url": "{q["url"]}",')
    print(f'        "arn": "{q["arn"]}",')
    print(f'    }},')
print("}")