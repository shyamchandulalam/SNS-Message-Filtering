import boto3
import json
from config import REGION, QUEUES

sqs = boto3.client("sqs", region_name=REGION)


def read_queue(label, queue_url):
    """Read and delete all messages in a queue."""
    response = sqs.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=1,
        MessageAttributeNames=["All"],
    )

    messages = response.get("Messages", [])
    print(f"\n📬 {label} ({len(messages)} messages):")

    if not messages:
        print("   (empty)")
        return

    for msg in messages:
        try:
            body = json.loads(msg["Body"])
            print(f"   → {body['order_id']} | ${body['price_usd']} | "
                  f"{body['category']} | {body['customer_tier']}")
        except Exception as e:
            print(f"   → (parse error) {msg['Body'][:80]}")

        # Delete after reading
        sqs.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=msg["ReceiptHandle"],
        )


if __name__ == "__main__":
    print("=" * 60)
    print("READING MESSAGES FROM ALL QUEUES")
    print("=" * 60)

    for key, info in QUEUES.items():
        read_queue(info["name"], info["url"])

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)