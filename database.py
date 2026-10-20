import os
import sqlite3

import psycopg2
import psycopg2.extras


DATABASE_URL = os.environ.get("DATABASE_URL")
LOCAL_DATABASE_PATH = os.environ.get("LOCAL_DATABASE_PATH", "social_engine_local.db")


class SQLiteCursor(sqlite3.Cursor):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def execute(self, query, parameters=()):
        query = query.replace("%s::date", "%s")
        query = query.replace("NOW()", "CURRENT_TIMESTAMP")
        query = query.replace("%s", "?")
        return super().execute(query, parameters)


class SQLiteConnection(sqlite3.Connection):
    def cursor(self, cursor_factory=None):
        return super().cursor(factory=SQLiteCursor)


def dict_row(cursor, row):
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


def get_db():
    if DATABASE_URL:
        return psycopg2.connect(
            DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )

    conn = sqlite3.connect(LOCAL_DATABASE_PATH, factory=SQLiteConnection)
    conn.row_factory = dict_row
    return conn
