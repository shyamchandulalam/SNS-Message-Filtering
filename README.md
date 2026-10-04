# SNS FilterHub — Amazon SNS Message Filtering Platform

[![Python 3.11](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/framework-Flask-lightgrey.svg)](https://palletsprojects.com/p/flask/)
[![AWS SNS](https://img.shields.io/badge/AWS-SNS-orange.svg)](https://aws.amazon.com/sns/)
[![AWS SQS](https://img.shields.io/badge/AWS-SQS-red.svg)](https://aws.amazon.com/sqs/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

> A production-grade multi-user SaaS platform demonstrating **selective message delivery** and **fanout** using **Amazon SNS Subscription Filter Policies**.

---

## 🎯 Value Proposition

> **"ONE MESSAGE → MULTIPLE USER FILTERS → SELECTIVE DELIVERY"**

Traditional pub/sub architectures broadcast every message to every subscriber, requiring subscribers to waste compute and bandwidth discarding irrelevant events. **Amazon SNS Subscription Filter Policies** solve this problem at the cloud messaging layer by evaluating message attributes before message fanout, ensuring each subscriber receives only the messages that match their exact subscription preferences.

---

## 🏗️ Architecture & Message Flow

```
                      +-----------------------------+
                      |   Admin Message Composer    |
                      +-----------------------------+
                                     |
                                     v
                       POST /api/admin/messages/publish
                      (with MessageAttributes: price,
                       category, tier, region, priority)
                                     |
                                     v
                   +-----------------------------------+
                   |   Amazon SNS: order-events-topic   |
                   +-----------------------------------+
                                     |
                                     | Evaluates Subscription Filter Policies
            +------------------------+------------------------+
            |                        |                        |
            v                        v                        v
+-----------------------+  +-------------------+  +-----------------------+
|  User A (Rahul)       |  |  User B (Priya)   |  |  User C (Sneha)       |
|  Filter Policy:       |  |  Filter Policy:   |  |  Filter Policy:       |
|  category=electronics |  |  tier=premium     |  |  region=US            |
+-----------------------+  +-------------------+  +-----------------------+
            |                        |                        |
     [MATCHED: ✓]             [MATCHED: ✓]             [FILTERED: ✕]
            |                        |                        |
            v                        v                        v
+-----------------------+  +-------------------+        (Dropped at SNS
| SQS: sns-user-2       |  | SQS: sns-user-3   |         no compute /
| User Inbox Received   |  | User Inbox Recv   |         zero noise)
+-----------------------+  +-------------------+
```

---

## 👥 Platform Roles & Permissions (RBAC)

| Role | Access Scope | Capabilities |
| :--- | :--- | :--- |
| **ADMIN** | System-wide (`/api/admin/*`) | • User Management (CRUD, status, reset password)<br>• Filter Policy Builder (multi-condition AND rules)<br>• Message Composer with live SNS publication<br>• Real-time Routing Analysis Tree (Matched vs Filtered)<br>• Message Activity Audit Log<br>• Persistent Database Analytics |
| **USER** | Personal sandbox (`/api/user/*`) | • Personalized Dashboard with greeting & metrics<br>• Dedicated Message Inbox (search, category filter, sort)<br>• Message Details inspection (payload, matched rule)<br>• Active Filters inspection (read-only)<br>• SQS Subscription endpoint & policy preview<br>• Real-time notifications & automatic polling |

---

## 🗄️ Database Schema (`sns_filterhub.db`)

The application uses persistent SQLite storage with foreign keys and salted PBKDF2 password hashing:

- **`users`**: `id`, `name`, `email` (UNIQUE), `password_hash`, `role` (ADMIN|USER), `status` (ACTIVE|DISABLED), `created_at`, `last_login`
- **`user_filters`**: `id`, `user_id`, `attribute_name`, `operator`, `attribute_value`, `enabled`, `created_at`
- **`subscriptions`**: `id`, `user_id`, `sns_topic_arn`, `sqs_queue_url`, `filter_policy` (JSON), `status`, `created_at`
- **`messages`**: `id`, `message_id`, `topic`, `payload` (JSON), `attributes` (JSON), `created_at`
- **`message_deliveries`**: `id`, `message_id`, `user_id`, `subscription_id`, `status` (DELIVERED|FILTERED), `reason`, `matched_at`, `delivered_at`
- **`notifications`**: `id`, `user_id`, `message_id`, `title`, `message`, `read_status`, `created_at`

---

## 🔑 Pre-Configured Demo Accounts (1-Click Login)

The login screen includes quick 1-click pills to log in as any role:

| Name | Role | Email | Password | Assigned Filter Policy |
| :--- | :--- | :--- | :--- | :--- |
| **System Administrator** | `ADMIN` | `admin@snsfilterhub.com` | `Admin@123` | *All Admin Controls* |
| **Rahul Kumar** | `USER` | `rahul@example.com` | `User@123` | `category = electronics` |
| **Priya Sharma** | `USER` | `priya@example.com` | `User@123` | `customer_tier = premium` |
| **Arjun Patel** | `USER` | `arjun@example.com` | `User@123` | `price_usd > 100` |
| **Sneha Reddy** | `USER` | `sneha@example.com` | `User@123` | `region = US` |
| **Vikram Singh** | `USER` | `vikram@example.com` | `User@123` | `priority = HIGH` |

---

## 🚀 Quickstart & Setup

### 1. Prerequisites
- Python 3.11+
- pip

### 2. Install Dependencies
```bash
pip install flask boto3 python-dotenv
```

### 3. Environment Configuration (Optional)
Copy `.env.example` to `.env` to configure live AWS credentials:
```bash
cp .env.example .env
```
```ini
AWS_REGION=us-east-1
SNS_TOPIC_ARN=arn:aws:sns:us-east-1:541645813476:order-events-topic
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
OPERATION_MODE=auto
SECRET_KEY=sns-filterhub-dev-secret-key-998877
```
> *Note: If AWS credentials are not configured, the platform automatically runs in high-fidelity **AWS Sandbox/Simulation Mode**, evaluating filter policy syntax locally with identical SNS evaluation semantics.*

### 4. Initialize & Seed Database
```bash
python seed.py
```

### 5. Launch the Application
```bash
python app.py
```
Open **[http://localhost:5000](http://localhost:5000)** in your browser.

---

## 🏆 Hackathon 10-Step Live Demo Scenario

Follow this live demo flow to demonstrate Amazon SNS selective message filtering:

1. **Step 1:** Open `http://localhost:5000` and click the **👑 Admin** demo pill to log in as Administrator.
2. **Step 2:** Navigate to **Users & Filters**. Show the 4 seeded users with different filter rules.
3. **Step 3:** Open **Rahul Kumar's** filters to verify rule: `category = electronics`.
4. **Step 4:** Navigate to **Message Composer**.
5. **Step 5:** Enter an order with attributes:
   - **Order ID:** `ORD-1001`
   - **Price:** `1500`
   - **Category:** `electronics`
   - **Customer Tier:** `premium`
   - **Priority:** `HIGH`
   - **Region:** `EU`
6. **Step 6:** Click **PUBLISH TO SNS**.
7. **Step 7:** Inspect the **Live Routing Analysis Tree**:
   - `Rahul Kumar`: **🟢 MATCHED · DELIVERED** (`category = electronics ✓`)
   - `Priya Sharma`: **🟢 MATCHED · DELIVERED** (`customer_tier = premium ✓`)
   - `Arjun Patel`: **🟢 MATCHED · DELIVERED** (`price_usd (1500) > 100 ✓`)
   - `Sneha Reddy`: **🔴 NOT MATCHED · FILTERED** (`region (EU) != US ✕`)
8. **Step 8:** Log out, then 1-click log in as **⚡ Rahul** (`rahul@example.com`).
   - Notice the unread notification badge.
   - Open **My Messages**; order `ORD-1001` is in his inbox with reason `category = electronics ✓`.
9. **Step 9:** Log out, then 1-click log in as **🇺🇸 Sneha** (`sneha@example.com`).
   - Notice that order `ORD-1001` was filtered out and **never reached Sneha's inbox**.
10. **Step 10:** Log back in as **👑 Admin** and open **Audit Log** to inspect the routing history.

---

## 🧪 Automated Testing

Run the comprehensive unit test suite:
```bash
python test_app.py
```
Tests cover:
- Authentication & password verification
- RBAC role enforcement (Admin vs User API boundaries)
- User data isolation (preventing cross-user data leakage)
- Dynamic filter compilation & SNS filter policy evaluation
- Message publishing, selective delivery, and user inbox routing
- Legacy simulator compatibility

---

## 🔌 API Reference

### Authentication
- `POST /api/auth/login` — Authenticate and start session
- `POST /api/auth/register` — Create new subscriber account
- `POST /api/auth/logout` — Terminate session
- `GET /api/auth/me` — Current authenticated session identity

### Admin Endpoints (`ADMIN` role required)
- `GET /api/admin/users` — List platform users with filter summaries
- `POST /api/admin/users` — Create user
- `GET /api/admin/users/<id>` — User details, filters, and subscriptions
- `PUT /api/admin/users/<id>` — Update user details / toggle active status
- `DELETE /api/admin/users/<id>` — Delete user
- `POST /api/admin/users/<id>/filters` — Add filter condition
- `PUT /api/admin/users/<id>/filters/<fid>` — Update filter condition
- `DELETE /api/admin/users/<id>/filters/<fid>` — Delete filter condition
- `POST /api/admin/messages/publish` — Publish message to SNS and evaluate routing
- `GET /api/admin/messages` — List published messages
- `GET /api/admin/routing/<msg_id>` — Detailed per-user routing analysis breakdown
- `GET /api/admin/analytics` — Dynamic analytics & delivery statistics
- `GET /api/admin/aws-status` — AWS SNS/SQS connectivity check

### User Endpoints (`USER` role required, strictly isolated)
- `GET /api/user/profile` — Logged-in subscriber profile
- `GET /api/user/dashboard` — User-specific dashboard stats & recent messages
- `GET /api/user/messages` — User inbox (supports `search`, `category`, `sort`)
- `GET /api/user/messages/<id>` — Message details (payload, matched filters)
- `GET /api/user/filters` — User's assigned filter rules
- `GET /api/user/subscription` — SQS queue endpoint & filter policy JSON
- `GET /api/user/notifications` — Notification alerts
- `PUT /api/user/notifications/<id>/read` — Mark notification read
- `PUT /api/user/notifications/read-all` — Mark all read
