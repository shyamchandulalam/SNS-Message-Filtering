from flask import Flask, render_template, request, jsonify, session
import json
import random
import time
from functools import wraps
import sqlite3
import os

from config import (
    REGION, TOPIC_ARN, QUEUES, SECRET_KEY, DATABASE_PATH, OPERATION_MODE
)
from database import (
    get_db, init_db, hash_password, verify_password
)
from filter_engine import (
    generate_sns_filter_policy, evaluate_user_filters
)
from aws_service import (
    publish_to_sns, sync_user_subscription_to_aws, test_aws_connection
)

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Ensure database tables exist on startup
init_db()

# In-memory published log for backward compatibility with legacy /log endpoint
published_log = []

# ═══════════════════════════════════════════════════════
# AUTH HELPERS & DECORATORS
# ═══════════════════════════════════════════════════════

def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = get_db()
    user = conn.execute(
        "SELECT id, name, email, role, status, created_at, last_login FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    if user and user["status"] == "ACTIVE":
        return dict(user)
    return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"status": "error", "message": "Unauthorized. Please log in."}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"status": "error", "message": "Unauthorized. Please log in."}), 401
        if user.get("role") != "ADMIN":
            return jsonify({"status": "error", "message": "Forbidden. Admin privileges required."}), 403
        return f(*args, **kwargs)
    return decorated_function

# ═══════════════════════════════════════════════════════
# MAIN ROUTE
# ═══════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")

# ═══════════════════════════════════════════════════════
# AUTHENTICATION ENDPOINTS
# ═══════════════════════════════════════════════════════

@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"status": "error", "message": "Email and password are required"}), 400

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email,)).fetchone()

    if not user:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid email or password"}), 401

    if not verify_password(user["password_hash"], password):
        conn.close()
        return jsonify({"status": "error", "message": "Invalid email or password"}), 401

    if user["status"] != "ACTIVE":
        conn.close()
        return jsonify({"status": "error", "message": "Account has been disabled by an administrator"}), 403

    # Update last login
    conn.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user["id"],))
    conn.commit()
    conn.close()

    session["user_id"] = user["id"]
    session["user_role"] = user["role"]

    return jsonify({
        "status": "ok",
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "status": user["status"]
        }
    })

@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"status": "ok", "message": "Logged out successfully"})

@app.route("/api/auth/register", methods=["POST"])
def auth_register():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not name or not email or not password:
        return jsonify({"status": "error", "message": "All fields are required"}), 400

    if len(password) < 6:
        return jsonify({"status": "error", "message": "Password must be at least 6 characters"}), 400

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE LOWER(email) = ?", (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"status": "error", "message": "Account with this email already exists"}), 409

    pwd_hash = hash_password(password)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (name, email, password_hash, role, status) VALUES (?, ?, ?, 'USER', 'ACTIVE')",
        (name, email, pwd_hash)
    )
    user_id = cursor.lastrowid

    # Create default subscription
    policy_json = "{}"
    aws_sub = sync_user_subscription_to_aws(user_id, TOPIC_ARN, {})
    cursor.execute(
        "INSERT INTO subscriptions (user_id, sns_topic_arn, sqs_queue_url, filter_policy, status) VALUES (?, ?, ?, ?, 'ACTIVE')",
        (user_id, TOPIC_ARN, aws_sub["queue_url"], policy_json)
    )

    # Welcome notification
    cursor.execute(
        "INSERT INTO notifications (user_id, title, message) VALUES (?, 'Welcome to SNS FilterHub', 'Your account has been created. Awaiting subscription filter assignment.')",
        (user_id,)
    )

    conn.commit()
    conn.close()

    session["user_id"] = user_id
    session["user_role"] = "USER"

    return jsonify({
        "status": "ok",
        "user": {
            "id": user_id,
            "name": name,
            "email": email,
            "role": "USER",
            "status": "ACTIVE"
        }
    })

@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    user = get_current_user()
    if not user:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401
    return jsonify({"status": "ok", "user": user})

# ═══════════════════════════════════════════════════════
# ADMIN API ENDPOINTS
# ═══════════════════════════════════════════════════════

@app.route("/api/admin/users", methods=["GET"])
@admin_required
def admin_list_users():
    conn = get_db()
    users_rows = conn.execute(
        "SELECT id, name, email, role, status, created_at, last_login FROM users ORDER BY id ASC"
    ).fetchall()

    users_list = []
    for u in users_rows:
        user_dict = dict(u)
        # Fetch user filters
        filters = conn.execute(
            "SELECT id, attribute_name, operator, attribute_value, enabled FROM user_filters WHERE user_id = ?",
            (u["id"],)
        ).fetchall()
        user_dict["filters"] = [dict(f) for f in filters]

        # Count messages delivered
        deliv_count = conn.execute(
            "SELECT COUNT(*) as count FROM message_deliveries WHERE user_id = ? AND status = 'DELIVERED'",
            (u["id"],)
        ).fetchone()["count"]
        user_dict["messages_received"] = deliv_count

        # Subscription details
        sub = conn.execute(
            "SELECT id, sqs_queue_url, filter_policy, status FROM subscriptions WHERE user_id = ?",
            (u["id"],)
        ).fetchone()
        user_dict["subscription"] = dict(sub) if sub else None

        users_list.append(user_dict)

    conn.close()
    return jsonify({"status": "ok", "users": users_list})

@app.route("/api/admin/users", methods=["POST"])
@admin_required
def admin_create_user():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip() or "User@123"
    role = data.get("role", "USER").upper()
    status = data.get("status", "ACTIVE").upper()
    filters_data = data.get("filters", [])

    if not name or not email:
        return jsonify({"status": "error", "message": "Name and email are required"}), 400

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE LOWER(email) = ?", (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"status": "error", "message": "User with this email already exists"}), 409

    cursor = conn.cursor()
    pwd_hash = hash_password(password)
    cursor.execute(
        "INSERT INTO users (name, email, password_hash, role, status) VALUES (?, ?, ?, ?, ?)",
        (name, email, pwd_hash, role, status)
    )
    user_id = cursor.lastrowid

    # Insert filters
    for f in filters_data:
        attr = f.get("attribute_name", "").strip()
        op = f.get("operator", "=").strip()
        val = str(f.get("attribute_value", "")).strip()
        if attr and val:
            cursor.execute(
                "INSERT INTO user_filters (user_id, attribute_name, operator, attribute_value, enabled) VALUES (?, ?, ?, ?, 1)",
                (user_id, attr, op, val)
            )

    # Sync subscription with AWS
    if role == "USER":
        policy = generate_sns_filter_policy(filters_data)
        policy_json = json.dumps(policy)
        aws_sub = sync_user_subscription_to_aws(user_id, TOPIC_ARN, policy)
        cursor.execute(
            "INSERT INTO subscriptions (user_id, sns_topic_arn, sqs_queue_url, filter_policy, status) VALUES (?, ?, ?, ?, ?)",
            (user_id, TOPIC_ARN, aws_sub["queue_url"], policy_json, "ACTIVE")
        )

        cursor.execute(
            "INSERT INTO notifications (user_id, title, message) VALUES (?, 'Subscription Configured', ?)",
            (user_id, f"Your subscription has been initialized with policy: {policy_json}")
        )

    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "message": "User created successfully", "user_id": user_id})

@app.route("/api/admin/users/<int:user_id>", methods=["GET"])
@admin_required
def admin_get_user(user_id):
    conn = get_db()
    u = conn.execute("SELECT id, name, email, role, status, created_at, last_login FROM users WHERE id = ?", (user_id,)).fetchone()
    if not u:
        conn.close()
        return jsonify({"status": "error", "message": "User not found"}), 404

    user_dict = dict(u)
    filters = conn.execute("SELECT id, attribute_name, operator, attribute_value, enabled FROM user_filters WHERE user_id = ?", (user_id,)).fetchall()
    user_dict["filters"] = [dict(f) for f in filters]

    sub = conn.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()
    user_dict["subscription"] = dict(sub) if sub else None

    # Recent deliveries for this user
    delivs = conn.execute(
        """SELECT md.id, md.message_id, md.status, md.reason, md.matched_at, m.topic, m.payload, m.attributes
           FROM message_deliveries md
           JOIN messages m ON md.message_id = m.message_id
           WHERE md.user_id = ?
           ORDER BY md.matched_at DESC LIMIT 10""",
        (user_id,)
    ).fetchall()
    user_dict["recent_deliveries"] = [dict(d) for d in delivs]

    conn.close()
    return jsonify({"status": "ok", "user": user_dict})

@app.route("/api/admin/users/<int:user_id>", methods=["PUT"])
@admin_required
def admin_update_user(user_id):
    data = request.get_json() or {}
    conn = get_db()
    u = conn.execute("SELECT id, email, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if not u:
        conn.close()
        return jsonify({"status": "error", "message": "User not found"}), 404

    name = data.get("name")
    role = data.get("role")
    status = data.get("status")
    password = data.get("password")

    updates = []
    params = []

    if name:
        updates.append("name = ?")
        params.append(name.strip())
    if role and role.upper() in ["ADMIN", "USER"]:
        updates.append("role = ?")
        params.append(role.upper())
    if status and status.upper() in ["ACTIVE", "DISABLED"]:
        updates.append("status = ?")
        params.append(status.upper())
    if password:
        updates.append("password_hash = ?")
        params.append(hash_password(password.strip()))

    if updates:
        params.append(user_id)
        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    conn.close()
    return jsonify({"status": "ok", "message": "User updated successfully"})

@app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
@admin_required
def admin_delete_user(user_id):
    current = get_current_user()
    if current and current["id"] == user_id:
        return jsonify({"status": "error", "message": "You cannot delete your own account"}), 400

    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "message": "User deleted successfully"})

@app.route("/api/admin/users/<int:user_id>/filters", methods=["POST"])
@admin_required
def admin_add_user_filter(user_id):
    data = request.get_json() or {}
    attr = data.get("attribute_name", "").strip()
    op = data.get("operator", "=").strip()
    val = str(data.get("attribute_value", "")).strip()

    if not attr or not val:
        return jsonify({"status": "error", "message": "Attribute name and value are required"}), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO user_filters (user_id, attribute_name, operator, attribute_value, enabled) VALUES (?, ?, ?, ?, 1)",
        (user_id, attr, op, val)
    )

    # Regenerate policy & sync
    filters = conn.execute("SELECT attribute_name, operator, attribute_value, enabled FROM user_filters WHERE user_id = ?", (user_id,)).fetchall()
    policy = generate_sns_filter_policy([dict(f) for f in filters])
    policy_json = json.dumps(policy)

    conn.execute("UPDATE subscriptions SET filter_policy = ? WHERE user_id = ?", (policy_json, user_id))
    sync_user_subscription_to_aws(user_id, TOPIC_ARN, policy)

    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "message": "Filter added and subscription policy updated", "policy": policy})

@app.route("/api/admin/users/<int:user_id>/filters/<int:filter_id>", methods=["PUT"])
@admin_required
def admin_update_user_filter(user_id, filter_id):
    data = request.get_json() or {}
    conn = get_db()

    updates = []
    params = []
    if "attribute_name" in data:
        updates.append("attribute_name = ?")
        params.append(data["attribute_name"].strip())
    if "operator" in data:
        updates.append("operator = ?")
        params.append(data["operator"].strip())
    if "attribute_value" in data:
        updates.append("attribute_value = ?")
        params.append(str(data["attribute_value"]).strip())
    if "enabled" in data:
        updates.append("enabled = ?")
        params.append(1 if data["enabled"] else 0)

    if updates:
        params.extend([filter_id, user_id])
        conn.execute(f"UPDATE user_filters SET {', '.join(updates)} WHERE id = ? AND user_id = ?", params)

    filters = conn.execute("SELECT attribute_name, operator, attribute_value, enabled FROM user_filters WHERE user_id = ?", (user_id,)).fetchall()
    policy = generate_sns_filter_policy([dict(f) for f in filters])
    policy_json = json.dumps(policy)

    conn.execute("UPDATE subscriptions SET filter_policy = ? WHERE user_id = ?", (policy_json, user_id))
    sync_user_subscription_to_aws(user_id, TOPIC_ARN, policy)

    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "message": "Filter updated", "policy": policy})

@app.route("/api/admin/users/<int:user_id>/filters/<int:filter_id>", methods=["DELETE"])
@admin_required
def admin_delete_user_filter(user_id, filter_id):
    conn = get_db()
    conn.execute("DELETE FROM user_filters WHERE id = ? AND user_id = ?", (filter_id, user_id))

    filters = conn.execute("SELECT attribute_name, operator, attribute_value, enabled FROM user_filters WHERE user_id = ?", (user_id,)).fetchall()
    policy = generate_sns_filter_policy([dict(f) for f in filters])
    policy_json = json.dumps(policy)

    conn.execute("UPDATE subscriptions SET filter_policy = ? WHERE user_id = ?", (policy_json, user_id))
    sync_user_subscription_to_aws(user_id, TOPIC_ARN, policy)

    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "message": "Filter removed", "policy": policy})

# ═══════════════════════════════════════════════════════
# ADMIN MESSAGE PUBLISHING & ROUTING ANALYSIS
# ═══════════════════════════════════════════════════════

@app.route("/api/admin/messages/publish", methods=["POST"])
@admin_required
def admin_publish_message():
    data = request.get_json() or {}

    order_id = data.get("order_id", "").strip() or f"ORD-{random.randint(1000, 9999)}"
    title = data.get("title", "").strip() or f"Order Alert: {order_id}"
    body = data.get("body", "").strip() or f"New order {order_id} has been processed."
    topic_arn = data.get("topic_arn", TOPIC_ARN)

    price_usd = float(data.get("price_usd", 100))
    category = data.get("category", "electronics").strip()
    customer_tier = data.get("customer_tier", "basic").strip()
    region = data.get("region", "US").strip()
    priority = data.get("priority", "HIGH").strip()

    attributes = {
        "price_usd": price_usd,
        "category": category,
        "customer_tier": customer_tier,
        "region": region,
        "priority": priority,
    }

    payload = {
        "order_id": order_id,
        "title": title,
        "body": body,
        "price_usd": price_usd,
        "category": category,
        "customer_tier": customer_tier,
        "region": region,
        "priority": priority,
        "timestamp": time.time(),
    }

    # 1. Publish to AWS SNS
    sns_result = publish_to_sns(topic_arn, payload, attributes)
    message_id = f"MSG-{order_id.replace('ORD-', '')}" if "ORD-" in order_id else f"MSG-{random.randint(1000, 9999)}"

    # 2. Store message in database
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (message_id, topic, payload, attributes) VALUES (?, ?, ?, ?)",
        (message_id, topic_arn, json.dumps(payload), json.dumps(attributes))
    )

    # 3. Retrieve all active users and evaluate subscription filters
    users = conn.execute("SELECT id, name, email FROM users WHERE role = 'USER' AND status = 'ACTIVE'").fetchall()

    routing_results = []
    delivered_count = 0
    filtered_count = 0

    for u in users:
        u_id = u["id"]
        filters = conn.execute(
            "SELECT attribute_name, operator, attribute_value, enabled FROM user_filters WHERE user_id = ?",
            (u_id,)
        ).fetchall()
        sub = conn.execute("SELECT id FROM subscriptions WHERE user_id = ?", (u_id,)).fetchone()
        sub_id = sub["id"] if sub else None

        eval_result = evaluate_user_filters([dict(f) for f in filters], attributes)

        if eval_result["matched"]:
            delivered_count += 1
            cursor.execute(
                """INSERT INTO message_deliveries (message_id, user_id, subscription_id, status, reason, matched_at, delivered_at)
                   VALUES (?, ?, ?, 'DELIVERED', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (message_id, u_id, sub_id, eval_result["reason"])
            )
            # Create user notification
            cursor.execute(
                """INSERT INTO notifications (user_id, message_id, title, message)
                   VALUES (?, ?, ?, ?)""",
                (u_id, message_id, f"Order {order_id} Alert", f"{title} — Matched: {eval_result['reason']}")
            )
            routing_results.append({
                "user_id": u_id,
                "name": u["name"],
                "email": u["email"],
                "status": "DELIVERED",
                "matched": True,
                "reason": eval_result["reason"],
                "details": eval_result["details"]
            })
        else:
            filtered_count += 1
            cursor.execute(
                """INSERT INTO message_deliveries (message_id, user_id, subscription_id, status, reason, matched_at)
                   VALUES (?, ?, ?, 'FILTERED', ?, CURRENT_TIMESTAMP)""",
                (message_id, u_id, sub_id, eval_result["reason"])
            )
            routing_results.append({
                "user_id": u_id,
                "name": u["name"],
                "email": u["email"],
                "status": "FILTERED",
                "matched": False,
                "reason": eval_result["reason"],
                "details": eval_result["details"]
            })

    conn.commit()
    conn.close()

    # Legacy simulator log tracking
    matched_queues = []
    if price_usd > 100: matched_queues.append("high_value")
    if category in ["electronics", "computers"]: matched_queues.append("electronics")
    if customer_tier in ["premium", "gold"]: matched_queues.append("premium")
    matched_queues.append("all")
    published_log.append({
        "order": payload,
        "matched_to": matched_queues,
        "timestamp": time.time()
    })
    if len(published_log) > 20: published_log.pop(0)

    return jsonify({
        "status": "ok",
        "message_id": message_id,
        "sns_result": sns_result,
        "payload": payload,
        "attributes": attributes,
        "summary": {
            "total_users": len(users),
            "delivered": delivered_count,
            "filtered": filtered_count,
            "rate": f"{(delivered_count / max(len(users), 1) * 100):.1f}%"
        },
        "routing": routing_results
    })

@app.route("/api/admin/routing/<message_id>", methods=["GET"])
@admin_required
def admin_get_routing(message_id):
    conn = get_db()
    msg = conn.execute("SELECT * FROM messages WHERE message_id = ?", (message_id,)).fetchone()
    if not msg:
        conn.close()
        return jsonify({"status": "error", "message": "Message not found"}), 404

    deliveries = conn.execute(
        """SELECT md.id, md.user_id, u.name, u.email, md.status, md.reason, md.matched_at, md.delivered_at
           FROM message_deliveries md
           JOIN users u ON md.user_id = u.id
           WHERE md.message_id = ?
           ORDER BY md.status ASC, u.name ASC""",
        (message_id,)
    ).fetchall()

    conn.close()
    return jsonify({
        "status": "ok",
        "message": {
            "message_id": msg["message_id"],
            "topic": msg["topic"],
            "payload": json.loads(msg["payload"]),
            "attributes": json.loads(msg["attributes"]),
            "created_at": msg["created_at"]
        },
        "routing": [dict(d) for d in deliveries]
    })

@app.route("/api/admin/messages", methods=["GET"])
@admin_required
def admin_list_messages():
    conn = get_db()
    msgs = conn.execute(
        """SELECT m.id, m.message_id, m.topic, m.payload, m.attributes, m.created_at,
                  SUM(CASE WHEN md.status = 'DELIVERED' THEN 1 ELSE 0 END) as delivered_count,
                  SUM(CASE WHEN md.status = 'FILTERED' THEN 1 ELSE 0 END) as filtered_count,
                  COUNT(md.id) as total_evaluated
           FROM messages m
           LEFT JOIN message_deliveries md ON m.message_id = md.message_id
           GROUP BY m.id
           ORDER BY m.id DESC LIMIT 50"""
    ).fetchall()

    result = []
    for m in msgs:
        d = dict(m)
        try: d["payload"] = json.loads(d["payload"])
        except Exception: pass
        try: d["attributes"] = json.loads(d["attributes"])
        except Exception: pass
        result.append(d)

    conn.close()
    return jsonify({"status": "ok", "messages": result})

@app.route("/api/admin/analytics", methods=["GET"])
@admin_required
def admin_get_analytics():
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) as count FROM users WHERE role = 'USER'").fetchone()["count"]
    active_users = conn.execute("SELECT COUNT(*) as count FROM users WHERE role = 'USER' AND status = 'ACTIVE'").fetchone()["count"]

    total_published = conn.execute("SELECT COUNT(*) as count FROM messages").fetchone()["count"]
    total_delivered = conn.execute("SELECT COUNT(*) as count FROM message_deliveries WHERE status = 'DELIVERED'").fetchone()["count"]
    total_filtered = conn.execute("SELECT COUNT(*) as count FROM message_deliveries WHERE status = 'FILTERED'").fetchone()["count"]
    total_evaluated = total_delivered + total_filtered

    rate = f"{(total_delivered / total_evaluated * 100):.1f}%" if total_evaluated > 0 else "0.0%"

    # Categories breakdown
    recent_msgs = conn.execute("SELECT attributes FROM messages ORDER BY id DESC LIMIT 50").fetchall()
    categories = {}
    for r in recent_msgs:
        try:
            attrs = json.loads(r["attributes"])
            cat = attrs.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
        except Exception:
            pass

    conn.close()
    return jsonify({
        "status": "ok",
        "analytics": {
            "total_users": total_users,
            "active_users": active_users,
            "messages_published": total_published,
            "messages_delivered": total_delivered,
            "messages_filtered": total_filtered,
            "delivery_rate": rate,
            "category_distribution": categories
        }
    })

@app.route("/api/admin/aws-status", methods=["GET"])
@admin_required
def admin_aws_status():
    status = test_aws_connection()
    return jsonify({"status": "ok", "aws": status})

# ═══════════════════════════════════════════════════════
# USER API ENDPOINTS (DATA ISOLATION ENFORCED)
# ═══════════════════════════════════════════════════════

@app.route("/api/user/profile", methods=["GET"])
@login_required
def user_profile():
    u = get_current_user()
    return jsonify({"status": "ok", "profile": u})

@app.route("/api/user/dashboard", methods=["GET"])
@login_required
def user_dashboard():
    u = get_current_user()
    user_id = u["id"]

    conn = get_db()
    # Stats
    rec_count = conn.execute(
        "SELECT COUNT(*) as count FROM message_deliveries WHERE user_id = ? AND status = 'DELIVERED'",
        (user_id,)
    ).fetchone()["count"]

    unread_count = conn.execute(
        "SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND read_status = 0",
        (user_id,)
    ).fetchone()["count"]

    filter_count = conn.execute(
        "SELECT COUNT(*) as count FROM user_filters WHERE user_id = ? AND enabled = 1",
        (user_id,)
    ).fetchone()["count"]

    sub = conn.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()

    # Recent messages (only this user's delivered messages)
    recent_msgs = conn.execute(
        """SELECT md.id, md.message_id, md.status, md.reason, md.matched_at, md.delivered_at,
                  m.topic, m.payload, m.attributes
           FROM message_deliveries md
           JOIN messages m ON md.message_id = m.message_id
           WHERE md.user_id = ? AND md.status = 'DELIVERED'
           ORDER BY md.matched_at DESC LIMIT 5""",
        (user_id,)
    ).fetchall()

    formatted_msgs = []
    for m in recent_msgs:
        item = dict(m)
        try: item["payload"] = json.loads(item["payload"])
        except Exception: pass
        try: item["attributes"] = json.loads(item["attributes"])
        except Exception: pass
        formatted_msgs.append(item)

    conn.close()

    return jsonify({
        "status": "ok",
        "stats": {
            "messages_received": rec_count,
            "unread_notifications": unread_count,
            "active_filters": filter_count,
            "subscription_status": sub["status"] if sub else "INACTIVE",
            "queue_name": f"sns-user-{user_id}"
        },
        "recent_messages": formatted_msgs
    })

@app.route("/api/user/messages", methods=["GET"])
@login_required
def user_get_messages():
    u = get_current_user()
    user_id = u["id"]

    search = request.args.get("search", "").strip().lower()
    category = request.args.get("category", "").strip().lower()
    sort = request.args.get("sort", "newest")

    order_by = "md.matched_at DESC" if sort == "newest" else "md.matched_at ASC"

    conn = get_db()
    rows = conn.execute(
        f"""SELECT md.id, md.message_id, md.status, md.reason, md.matched_at, md.delivered_at,
                   m.topic, m.payload, m.attributes
            FROM message_deliveries md
            JOIN messages m ON md.message_id = m.message_id
            WHERE md.user_id = ? AND md.status = 'DELIVERED'
            ORDER BY {order_by}""",
        (user_id,)
    ).fetchall()

    messages = []
    for r in rows:
        item = dict(r)
        try: item["payload"] = json.loads(item["payload"])
        except Exception: item["payload"] = {}
        try: item["attributes"] = json.loads(item["attributes"])
        except Exception: item["attributes"] = {}

        # Search filter
        title = item["payload"].get("title", "")
        body = item["payload"].get("body", "")
        order_id = item["payload"].get("order_id", "")
        msg_id = item["message_id"]

        if search:
            combined = f"{title} {body} {order_id} {msg_id}".lower()
            if search not in combined:
                continue

        if category and category != "all":
            msg_cat = str(item["attributes"].get("category", "")).lower()
            if msg_cat != category:
                continue

        messages.append(item)

    conn.close()
    return jsonify({"status": "ok", "messages": messages})

@app.route("/api/user/messages/<int:delivery_id>", methods=["GET"])
@login_required
def user_get_message_detail(delivery_id):
    u = get_current_user()
    user_id = u["id"]

    conn = get_db()
    row = conn.execute(
        """SELECT md.id, md.message_id, md.status, md.reason, md.matched_at, md.delivered_at,
                  m.topic, m.payload, m.attributes
           FROM message_deliveries md
           JOIN messages m ON md.message_id = m.message_id
           WHERE md.id = ? AND md.user_id = ?""",
        (delivery_id, user_id)
    ).fetchone()
    conn.close()

    if not row:
        return jsonify({"status": "error", "message": "Message not found or access denied"}), 404

    item = dict(row)
    try: item["payload"] = json.loads(item["payload"])
    except Exception: pass
    try: item["attributes"] = json.loads(item["attributes"])
    except Exception: pass

    return jsonify({"status": "ok", "message": item})

@app.route("/api/user/filters", methods=["GET"])
@login_required
def user_get_filters():
    u = get_current_user()
    user_id = u["id"]

    conn = get_db()
    filters = conn.execute(
        "SELECT id, attribute_name, operator, attribute_value, enabled, created_at FROM user_filters WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    conn.close()

    return jsonify({"status": "ok", "filters": [dict(f) for f in filters]})

@app.route("/api/user/subscription", methods=["GET"])
@login_required
def user_get_subscription():
    u = get_current_user()
    user_id = u["id"]

    conn = get_db()
    sub = conn.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()
    filters = conn.execute("SELECT attribute_name, operator, attribute_value, enabled FROM user_filters WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()

    filter_policy = generate_sns_filter_policy([dict(f) for f in filters])

    return jsonify({
        "status": "ok",
        "subscription": {
            "topic_arn": sub["sns_topic_arn"] if sub else TOPIC_ARN,
            "queue_url": sub["sqs_queue_url"] if sub else f"https://sqs.{REGION}.amazonaws.com/541645813476/sns-user-{user_id}",
            "queue_name": f"sns-user-{user_id}",
            "status": sub["status"] if sub else "ACTIVE",
            "filter_policy": filter_policy
        }
    })

@app.route("/api/user/notifications", methods=["GET"])
@login_required
def user_get_notifications():
    u = get_current_user()
    user_id = u["id"]

    conn = get_db()
    notifs = conn.execute(
        "SELECT id, message_id, title, message, read_status, created_at FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 30",
        (user_id,)
    ).fetchall()
    conn.close()

    return jsonify({"status": "ok", "notifications": [dict(n) for n in notifs]})

@app.route("/api/user/notifications/<int:notif_id>/read", methods=["PUT"])
@login_required
def user_mark_notif_read(notif_id):
    u = get_current_user()
    user_id = u["id"]

    conn = get_db()
    conn.execute("UPDATE notifications SET read_status = 1 WHERE id = ? AND user_id = ?", (notif_id, user_id))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "message": "Notification marked as read"})

@app.route("/api/user/notifications/read-all", methods=["PUT"])
@login_required
def user_mark_all_read():
    u = get_current_user()
    user_id = u["id"]

    conn = get_db()
    conn.execute("UPDATE notifications SET read_status = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "message": "All notifications marked as read"})

@app.route("/api/user/notifications/clear", methods=["DELETE"])
@login_required
def user_clear_notifications():
    u = get_current_user()
    user_id = u["id"]

    conn = get_db()
    conn.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "message": "All notifications cleared"})

# ═══════════════════════════════════════════════════════
# PRESERVED LEGACY SIMULATOR ENDPOINTS
# ═══════════════════════════════════════════════════════

@app.route("/publish", methods=["POST"])
def publish():
    """Preserved endpoint for legacy simulator and test scripts."""
    data = request.json or {}
    price = float(data.get("price_usd", 100))
    category = data.get("category", "electronics")
    customer_tier = data.get("customer_tier", "basic")

    order_id = f"ORD-{random.randint(10000, 99999)}"
    message = {
        "order_id": order_id,
        "price_usd": price,
        "category": category,
        "customer_tier": customer_tier,
    }

    publish_to_sns(TOPIC_ARN, message, {
        "price_usd": price,
        "category": category,
        "customer_tier": customer_tier
    })

    matched = []
    if price > 100: matched.append("high_value")
    if category in ["electronics", "computers"]: matched.append("electronics")
    if customer_tier in ["premium", "gold"]: matched.append("premium")
    matched.append("all")

    entry = {
        "order": message,
        "matched_to": matched,
        "timestamp": time.time(),
    }
    published_log.append(entry)
    if len(published_log) > 20: published_log.pop(0)

    return jsonify({"status": "ok", "entry": entry})

@app.route("/poll")
def poll():
    """Preserved endpoint for legacy polling of the 4 demo queues."""
    result = {}
    for key, info in QUEUES.items():
        result[key] = []
    return jsonify(result)

@app.route("/log")
def get_log():
    return jsonify(published_log[-20:])

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  SNS FilterHub — Multi-User Selective Message Delivery Platform")
    print("  Open: http://localhost:5000")
    print("  Default Admin: admin@snsfilterhub.com (Password: Admin@123)")
    print("=" * 60 + "\n")
    app.run(debug=True, port=5000)