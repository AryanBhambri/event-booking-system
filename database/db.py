"""Small MySQL connection helper used by feature routes."""
from flask import current_app
import mysql.connector
from mysql.connector import Error


def get_db_connection():
    """Return a new MySQL connection using Flask configuration.

    Routes should close the returned connection after use. mysql-connector
    parameterizes values supplied to cursor.execute(), helping avoid SQL injection.
    """
    try:
        return mysql.connector.connect(
            host=current_app.config["MYSQL_HOST"],
            port=current_app.config["MYSQL_PORT"],
            user=current_app.config["MYSQL_USER"],
            password=current_app.config["MYSQL_PASSWORD"],
            database=current_app.config["MYSQL_DATABASE"],
            connection_timeout=current_app.config["MYSQL_CONNECT_TIMEOUT"],
            ssl_ca=current_app.config["MYSQL_SSL_CA"],
            ssl_verify_cert=bool(current_app.config["MYSQL_SSL_CA"]),
            ssl_verify_identity=bool(current_app.config["MYSQL_SSL_CA"]),
        )
    except Error as error:
        current_app.logger.error("MySQL connection failed (error %s).", error.errno)
        raise
