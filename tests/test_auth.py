"""Integration checks for Phase 2 authentication against the configured MySQL database.

Run with: py -m tests.test_auth
The script creates temporary users and removes them in a finally block.
"""
from uuid import uuid4

from app import create_app
from tests.helpers import CSRFClient
from database.db import get_db_connection


EMAIL = f"phase2-test-{uuid4().hex[:12]}@example.test"
PASSWORD = "Phase2Test9"


def remove_test_user(app):
    """Remove the temporary test account after checks finish."""
    with app.app_context():
        connection = get_db_connection()
        cursor = connection.cursor()
        try:
            cursor.execute("DELETE FROM users WHERE email = %s", (EMAIL,))
            connection.commit()
        finally:
            cursor.close()
            connection.close()


def main():
    app = create_app()
    app.config.update(TESTING=True)
    app.test_client_class = CSRFClient
    client = app.test_client()
    remove_test_user(app)
    try:
        assert client.get("/dashboard/").status_code == 302
        assert client.get("/admin/").status_code == 302

        invalid = client.post("/auth/register", data={"name": "A", "email": "bad", "password": "weak", "confirm_password": "different"})
        assert invalid.status_code == 400
        registration = client.post("/auth/register", data={"name": "Phase Two Test", "email": EMAIL, "password": PASSWORD, "confirm_password": PASSWORD})
        assert registration.status_code == 302
        duplicate = client.post("/auth/register", data={"name": "Phase Two Test", "email": EMAIL, "password": PASSWORD, "confirm_password": PASSWORD})
        assert duplicate.status_code == 409

        wrong_password = client.post("/auth/login", data={"email": EMAIL, "password": "WrongPassword9"})
        assert wrong_password.status_code == 401
        login = client.post("/auth/login", data={"email": EMAIL, "password": PASSWORD})
        assert login.status_code == 302 and login.location.endswith("/dashboard/")
        assert client.get("/dashboard/").status_code == 200
        assert client.get("/admin/").status_code == 302

        assert client.post("/auth/logout").status_code == 302
        assert client.get("/dashboard/").status_code == 302
        with app.app_context():
            connection = get_db_connection()
            cursor = connection.cursor()
            try:
                cursor.execute("UPDATE users SET role = 'admin' WHERE email = %s", (EMAIL,))
                connection.commit()
            finally:
                cursor.close()
                connection.close()
        admin_login = client.post("/auth/login", data={"email": EMAIL, "password": PASSWORD})
        assert admin_login.status_code == 302 and admin_login.location.endswith("/admin/")
        assert client.get("/admin/").status_code == 200
        print("Authentication integration tests passed.")
    finally:
        remove_test_user(app)


if __name__ == "__main__":
    main()
