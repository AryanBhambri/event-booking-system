"""Smoke tests for Evently's public About page."""
from app import create_app
from tests.helpers import CSRFClient


def main():
    app = create_app()
    app.config.update(TESTING=True)
    app.test_client_class = CSRFClient
    anonymous_client = app.test_client()
    user_client = app.test_client()
    admin_client = app.test_client()

    home = anonymous_client.get("/")
    about = anonymous_client.get("/about")
    assert home.status_code == 200 and b'href="/about"' in home.data
    assert about.status_code == 200 and b"ABOUT EVENTLY" in about.data and b"site-footer" in about.data
    with user_client.session_transaction() as session:
        session.update(user_id=1, user_name="Test User", role="user")
    with admin_client.session_transaction() as session:
        session.update(user_id=2, user_name="Test Admin", role="admin")
    assert user_client.get("/about").status_code == 200
    assert admin_client.get("/about").status_code == 200
    print("About page integration tests passed.")


if __name__ == "__main__":
    main()
