import psycopg2
from .._endpoints import PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DATABASE


def get_connection_and_cursor(secret_name=None):
    """Real tenant reads creds from Secrets Manager keyed by secret_name; in the
    sandbox we ignore secret_name and connect to the seeded local Postgres."""
    connection = psycopg2.connect(
        host=PG_HOST, port=PG_PORT,
        user=PG_USER, password=PG_PASSWORD, dbname=PG_DATABASE,
    )
    cursor = connection.cursor()
    return cursor, connection
