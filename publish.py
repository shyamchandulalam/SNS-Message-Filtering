import boto3
import json
from config import REGION, TOPIC_ARN

sns = boto3.client("sns", region_name=REGION)


def publish_order(order_id, price, category, customer_tier):
    message = {
        "order_id": order_id,
        "item": f"Item-{order_id}",
        "price_usd": price,
        "category": category,
        "customer_tier": customer_tier,
    }

    response = sns.publish(
        TopicArn=TOPIC_ARN,
        Message=json.dumps(message),
        MessageAttributes={
            "price_usd": {"DataType": "Number", "StringValue": str(price)},
            "category": {"DataType": "String", "StringValue": category},
            "customer_tier": {"DataType": "String", "StringValue": customer_tier},
        },
    )
    print(f"✅ Published: {order_id} | ${price} | {category} | {customer_tier}")
    return response


if __name__ == "__main__":
    print("Publishing test orders...\n")

    # Test 1: High-value electronics order (premium customer)
    # Expected: ALL 4 queues
    publish_order("ORD-001", 1500.00, "electronics", "premium")

    # Test 2: Low-value book order (basic customer)
    # Expected: only "all-orders-queue"
    publish_order("ORD-002", 25.00, "books", "basic")

    # Test 3: High-value clothing (silver customer)
    # Expected: high-value + all
    publish_order("ORD-003", 250.00, "clothing", "silver")

    # Test 4: Cheap laptop (gold customer)
    # Expected: electronics + premium + all
    publish_order("ORD-004", 80.00, "computers", "gold")

    # Test 5: Mid-price food (basic)
    # Expected: only all-orders-queue
    publish_order("ORD-005", 45.00, "food", "basic")

    print("\n✅ All messages published!")
    print("Now run: python consume.py")