from flask import Flask, render_template, request, jsonify
import boto3
import json
import random
import time
from config import REGION, TOPIC_ARN, QUEUES

app = Flask(__name__)
sns = boto3.client("sns", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)

# Track published messages for display
published_log = []


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/publish", methods=["POST"])
def publish():
    data = request.json
    price = float(data["price_usd"])
    category = data["category"]
    customer_tier = data["customer_tier"]

    order_id = f"ORD-{random.randint(10000, 99999)}"
    message = {
        "order_id": order_id,
        "price_usd": price,
        "category": category,
        "customer_tier": customer_tier,
    }

    # Publish to SNS with attributes
    sns.publish(
        TopicArn=TOPIC_ARN,
        Message=json.dumps(message),
        MessageAttributes={
            "price_usd": {"DataType": "Number", "StringValue": str(price)},
            "category": {"DataType": "String", "StringValue": category},
            "customer_tier": {"DataType": "String", "StringValue": customer_tier},
        },
    )

    # Predict which queues should get it
    matched = []
    if price > 100:
        matched.append("high_value")
    if category in ["electronics", "computers"]:
        matched.append("electronics")
    if customer_tier in ["premium", "gold"]:
        matched.append("premium")
    matched.append("all")

    entry = {
        "order": message,
        "matched_to": matched,
        "timestamp": time.time(),
    }
    published_log.append(entry)
    if len(published_log) > 20:
        published_log.pop(0)

    return jsonify({"status": "ok", "entry": entry})


@app.route("/poll")
def poll():
    """Poll all queues once — fetch and delete messages."""
    result = {}
    for key, info in QUEUES.items():
        try:
            response = sqs.receive_message(
                QueueUrl=info["url"],
                MaxNumberOfMessages=10,
                WaitTimeSeconds=1,
                MessageAttributeNames=["All"],
            )
            msgs = []
            for m in response.get("Messages", []):
                try:
                    body = json.loads(m["Body"])
                except Exception:
                    body = {"raw": m["Body"][:100]}
                msgs.append(body)
                # Delete from queue after reading
                sqs.delete_message(
                    QueueUrl=info["url"],
                    ReceiptHandle=m["ReceiptHandle"],
                )
            result[key] = msgs
        except Exception as e:
            result[key] = []
    return jsonify(result)


@app.route("/log")
def get_log():
    return jsonify(published_log[-20:])


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  SNS Message Filtering Dashboard")
    print("  Open: http://localhost:5000")
    print("=" * 60 + "\n")
    app.run(debug=True, port=5000)