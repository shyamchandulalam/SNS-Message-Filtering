import json
from database import init_db, get_db, hash_password
from filter_engine import generate_sns_filter_policy
from aws_service import sync_user_subscription_to_aws
from config import TOPIC_ARN

def seed():
    print("Initializing SQLite database...")
    init_db()

    conn = get_db()
    cursor = conn.cursor()

    # Clear existing seed data to ensure fresh demo state
    cursor.execute("DELETE FROM notifications")
    cursor.execute("DELETE FROM message_deliveries")
    cursor.execute("DELETE FROM messages")
    cursor.execute("DELETE FROM subscriptions")
    cursor.execute("DELETE FROM user_filters")
    cursor.execute("DELETE FROM users")
    conn.commit()

    print("Seeding Users...")
    users_data = [
        {
            "name": "System Administrator",
            "email": "admin@snsfilterhub.com",
            "password": "Admin@123",
            "role": "ADMIN",
            "status": "ACTIVE",
            "filters": []
        },
        {
            "name": "Rahul Kumar",
            "email": "rahul@example.com",
            "password": "User@123",
            "role": "USER",
            "status": "ACTIVE",
            "filters": [
                {"attribute_name": "category", "operator": "=", "attribute_value": "electronics"}
            ]
        },
        {
            "name": "Priya Sharma",
            "email": "priya@example.com",
            "password": "User@123",
            "role": "USER",
            "status": "ACTIVE",
            "filters": [
                {"attribute_name": "customer_tier", "operator": "=", "attribute_value": "premium"}
            ]
        },
        {
            "name": "Arjun Patel",
            "email": "arjun@example.com",
            "password": "User@123",
            "role": "USER",
            "status": "ACTIVE",
            "filters": [
                {"attribute_name": "price_usd", "operator": ">", "attribute_value": "100"}
            ]
        },
        {
            "name": "Sneha Reddy",
            "email": "sneha@example.com",
            "password": "User@123",
            "role": "USER",
            "status": "ACTIVE",
            "filters": [
                {"attribute_name": "region", "operator": "=", "attribute_value": "US"}
            ]
        }
    ]

    for u in users_data:
        pwd_hash = hash_password(u["password"])
        cursor.execute(
            """INSERT INTO users (name, email, password_hash, role, status)
               VALUES (?, ?, ?, ?, ?)""",
            (u["name"], u["email"], pwd_hash, u["role"], u["status"])
        )
        user_id = cursor.lastrowid

        # Insert filters
        for f in u["filters"]:
            cursor.execute(
                """INSERT INTO user_filters (user_id, attribute_name, operator, attribute_value, enabled)
                   VALUES (?, ?, ?, ?, 1)""",
                (user_id, f["attribute_name"], f["operator"], f["attribute_value"])
            )

        # Generate SNS policy and Subscription
        if u["role"] == "USER":
            policy = generate_sns_filter_policy(u["filters"])
            policy_json = json.dumps(policy)
            aws_sub = sync_user_subscription_to_aws(user_id, TOPIC_ARN, policy)

            cursor.execute(
                """INSERT INTO subscriptions (user_id, sns_topic_arn, sqs_queue_url, filter_policy, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, TOPIC_ARN, aws_sub["queue_url"], policy_json, "ACTIVE")
            )

            # Welcome notification
            cursor.execute(
                """INSERT INTO notifications (user_id, title, message, read_status)
                   VALUES (?, ?, ?, ?)""",
                (user_id, "Welcome to SNS FilterHub", f"Your subscription is active with filter: {policy_json}", 0)
            )

    conn.commit()
    conn.close()

    print("=" * 60)
    print("DEMO SEED DATA CREATED SUCCESSFULLY!")
    print("=" * 60)
    print("Admin:")
    print("  Email:    admin@snsfilterhub.com")
    print("  Password: Admin@123 (Role: ADMIN)")
    print("\nUsers:")
    print("  Rahul:    rahul@example.com / User@123 (Filter: category = electronics)")
    print("  Priya:    priya@example.com / User@123 (Filter: customer_tier = premium)")
    print("  Arjun:    arjun@example.com / User@123 (Filter: price_usd > 100)")
    print("  Sneha:    sneha@example.com / User@123 (Filter: region = US)")
    print("=" * 60)

if __name__ == "__main__":
    seed()
