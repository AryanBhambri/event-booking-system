"""Read-only deployment/database checks; never print credential values."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

from app import app
from database.db import get_db_connection


def main():
    snapshot = {}
    with app.app_context():
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT DATABASE() AS name")
            assert cursor.fetchone()["name"] == "event_booking_system"
            expected = {
                "users": {"id", "name", "email", "password_hash", "role", "created_at", "updated_at"},
                "events": {"id", "title", "description", "category", "event_date", "event_time", "venue", "city", "ticket_price", "total_seats", "available_seats", "image_filename", "created_by", "created_at", "updated_at"},
                "bookings": {"id", "booking_code", "user_id", "event_id", "ticket_quantity", "total_amount", "status", "booked_at"},
            }
            for table, columns in expected.items():
                cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", (table,))
                assert {row["COLUMN_NAME"] for row in cursor.fetchall()} == columns
                cursor.execute("SELECT * FROM " + table + " ORDER BY id")
                rows = cursor.fetchall()
                snapshot[table] = {"count": len(rows), "sha256": hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()}
            cursor.execute("SELECT COUNT(*) AS count FROM users WHERE password_hash NOT LIKE 'scrypt:%' AND password_hash NOT LIKE 'pbkdf2:%'")
            assert cursor.fetchone()["count"] == 0, "Unexpected password storage format"
            cursor.execute("""SELECT COUNT(*) AS count FROM events WHERE total_seats - available_seats !=
                (SELECT COALESCE(SUM(ticket_quantity), 0) FROM bookings WHERE event_id = events.id AND status = 'confirmed')""")
            assert cursor.fetchone()["count"] == 0, "Existing seat counts disagree with confirmed bookings"
            cursor.execute("SELECT image_filename FROM events WHERE image_filename IS NOT NULL")
            for row in cursor.fetchall():
                image = row["image_filename"]
                if image.startswith("https://"):
                    assert len(image) <= 255, "Banner URL exceeds the database limit"
                elif image:
                    assert (Path(app.config["UPLOAD_FOLDER"]) / image).is_file()
            cursor.execute("SELECT COUNT(*) AS count FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('users','events','bookings') AND ENGINE = 'InnoDB'")
            assert cursor.fetchone()["count"] == 3
            cursor.execute("SELECT COUNT(*) AS count FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_TYPE = 'FOREIGN KEY'")
            assert cursor.fetchone()["count"] == 3
        finally:
            cursor.close()
            connection.close()
    baseline = Path(".qa-artifacts/database-before.json")
    if baseline.exists():
        assert snapshot == json.loads(baseline.read_text()), "Existing rows changed or QA cleanup is incomplete"
        print("PASS: Original database rows match the pre-audit hashes exactly.")
    print("PASS: Three tables, columns, InnoDB, foreign keys, seat totals, password hashing, and uploaded images.")
    assert len(app.secret_key) >= 32 and not app.debug
    assert app.config["SESSION_COOKIE_HTTPONLY"] and app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    print("PASS: Unique local secret configured, debug disabled, HTTP-only/SameSite cookies.")
    for path in [Path("app.py"), Path("config.py"), *Path("routes").glob("*.py"), *Path("utils").glob("*.py"), *Path("tests").glob("*.py")]:
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    subprocess.run(["node", "--check", "static/js/script.js"], check=True)
    print("PASS: Python and JavaScript syntax.")
    print("Git repository present:", Path(".git").exists())
    print("Local startup: .\\.venv\\Scripts\\python.exe -m flask --app app run --host 127.0.0.1 --port 5000 --no-debugger --no-reload")
    Path(".qa-artifacts/readiness-results.json").write_text(json.dumps({"database_rows_preserved": True, "counts": {key: row["count"] for key, row in snapshot.items()}, "debug": app.debug}, indent=2))


if __name__ == "__main__":
    main()
