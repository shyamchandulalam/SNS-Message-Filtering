import unittest
import json
import os
from app import app
from database import init_db, get_db, hash_password
from seed import seed

class SNSFilterHubTestCase(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret-key"
        self.client = app.test_client()
        # Seed test database
        seed()

    def login(self, email, password):
        return self.client.post(
            "/api/auth/login",
            data=json.dumps({"email": email, "password": password}),
            content_type="application/json"
        )

    def test_01_auth_flow(self):
        # Invalid password
        res = self.login("admin@snsfilterhub.com", "WrongPassword")
        self.assertEqual(res.status_code, 401)

        # Valid admin login
        res = self.login("admin@snsfilterhub.com", "Admin@123")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["user"]["role"], "ADMIN")

        # Valid user login
        res = self.login("rahul@example.com", "User@123")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["user"]["role"], "USER")

    def test_02_rbac_access_control(self):
        # User tries to access admin API -> should be 403 Forbidden
        self.login("rahul@example.com", "User@123")
        res = self.client.get("/api/admin/users")
        self.assertEqual(res.status_code, 403)

        # Admin accesses admin API -> 200 OK
        self.login("admin@snsfilterhub.com", "Admin@123")
        res = self.client.get("/api/admin/users")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(len(data["users"]) >= 4)

    def test_03_user_data_isolation(self):
        # Login as Rahul (id=2)
        self.login("rahul@example.com", "User@123")
        res = self.client.get("/api/user/filters")
        self.assertEqual(res.status_code, 200)
        filters = res.get_json()["filters"]
        # Rahul has filter category = electronics
        self.assertTrue(any(f["attribute_name"] == "category" and f["attribute_value"] == "electronics" for f in filters))
        # Ensure Rahul cannot see Priya's customer_tier filter
        self.assertFalse(any(f["attribute_name"] == "customer_tier" for f in filters))

    def test_04_message_publish_and_selective_routing(self):
        self.login("admin@snsfilterhub.com", "Admin@123")

        # Publish Order: $1500, electronics, premium, priority HIGH, region EU
        # Rahul: category=electronics -> MATCH
        # Priya: customer_tier=premium -> MATCH
        # Arjun: price_usd>100 ($1500) -> MATCH
        # Sneha: region=US (msg has EU) -> FILTERED
        payload = {
            "order_id": "ORD-1001",
            "title": "Flash Sale Order",
            "body": "Electronics premium order above 1000",
            "price_usd": 1500,
            "category": "electronics",
            "customer_tier": "premium",
            "priority": "HIGH",
            "region": "EU"
        }
        res = self.client.post("/api/admin/messages/publish", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        routing = {r["name"]: r["status"] for r in data["routing"]}

        self.assertEqual(routing["Rahul Kumar"], "DELIVERED")
        self.assertEqual(routing["Priya Sharma"], "DELIVERED")
        self.assertEqual(routing["Arjun Patel"], "DELIVERED")
        self.assertEqual(routing["Sneha Reddy"], "FILTERED")

        # Verify Rahul sees the message in his inbox
        self.login("rahul@example.com", "User@123")
        msg_res = self.client.get("/api/user/messages")
        self.assertEqual(msg_res.status_code, 200)
        rahul_msgs = msg_res.get_json()["messages"]
        self.assertTrue(any(m["payload"].get("order_id") == "ORD-1001" for m in rahul_msgs))

        # Verify Sneha does NOT see the message
        self.login("sneha@example.com", "User@123")
        sneha_res = self.client.get("/api/user/messages")
        self.assertEqual(sneha_res.status_code, 200)
        sneha_msgs = sneha_res.get_json()["messages"]
        self.assertFalse(any(m["payload"].get("order_id") == "ORD-1001" for m in sneha_msgs))

    def test_05_admin_user_management(self):
        self.login("admin@snsfilterhub.com", "Admin@123")

        # Create new user
        new_user = {
            "name": "Kavita Verma",
            "email": "kavita@example.com",
            "password": "User@123",
            "role": "USER",
            "status": "ACTIVE",
            "filters": [
                {"attribute_name": "priority", "operator": "=", "attribute_value": "HIGH"}
            ]
        }
        res = self.client.post("/api/admin/users", data=json.dumps(new_user), content_type="application/json")
        self.assertEqual(res.status_code, 200)
        uid = res.get_json()["user_id"]

        # Fetch created user
        res = self.client.get(f"/api/admin/users/{uid}")
        self.assertEqual(res.status_code, 200)
        u_data = res.get_json()["user"]
        self.assertEqual(u_data["name"], "Kavita Verma")
        self.assertEqual(len(u_data["filters"]), 1)

    def test_06_legacy_endpoints(self):
        # Legacy /publish
        res = self.client.post("/publish", data=json.dumps({
            "price_usd": 250,
            "category": "electronics",
            "customer_tier": "gold"
        }), content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

        # Legacy /log
        res = self.client.get("/log")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(len(res.get_json()) > 0)

if __name__ == "__main__":
    unittest.main()
