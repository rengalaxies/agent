"""Trusted isolated-interpreter worker for the internal read-only SQLite profile."""
import json
import math
import re
import resource
import sqlite3
import sys

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")
TYPES = {"INTEGER", "REAL", "TEXT"}
FUNCTIONS = {"sum", "total", "count", "avg", "min", "max", "abs", "round",
             "coalesce", "ifnull", "nullif", "length", "lower", "upper", "substr", "typeof"}


def response(status, reason=None, actual=None):
    return {"status": status, "actual": actual, "reason_codes": [reason] if reason else []}


def identifier(value):
    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        raise ValueError("invalid_fixture")
    return '"' + value + '"'


def build_fixture(conn, fixture):
    if type(fixture) is not dict or set(fixture) != {"schemas", "tables"}:
        raise ValueError("invalid_fixture")
    schemas, tables = fixture["schemas"], fixture["tables"]
    if (type(schemas) is not dict or type(tables) is not dict or not schemas
            or set(schemas) != set(tables) or len(schemas) > 16):
        raise ValueError("invalid_fixture")
    total_rows = 0
    for table, schema in schemas.items():
        name = identifier(table)
        if type(schema) is not dict or not 0 < len(schema) <= 128:
            raise ValueError("invalid_fixture")
        columns = []
        for col, kind in schema.items():
            if type(kind) is not str or kind not in TYPES:
                raise ValueError("unsupported_fixture_type")
            columns.append(identifier(col) + " " + kind)
        rows = tables[table]
        if type(rows) is not list:
            raise ValueError("invalid_fixture")
        total_rows += len(rows)
        if total_rows > 10_000:
            raise ValueError("fixture_row_limit")
        conn.execute("CREATE TABLE " + name + " (" + ",".join(columns) + ")")
        for row in rows:
            if type(row) is not dict or set(row) != set(schema):
                raise ValueError("invalid_fixture")
            for col, kind in schema.items():
                value = row[col]
                if value is None:
                    continue
                if kind == "INTEGER" and (type(value) is not int or not -(2**63) <= value < 2**63):
                    raise ValueError("invalid_fixture_value")
                if kind == "REAL" and (type(value) not in (int, float) or not math.isfinite(value)):
                    raise ValueError("invalid_fixture_value")
                if kind == "TEXT" and (type(value) is not str or len(value) > 16_384):
                    raise ValueError("invalid_fixture_value")
            conn.execute("INSERT INTO " + name + " VALUES (" + ",".join("?" for _ in schema) + ")",
                         tuple(row[col] for col in schema))
    conn.commit()


def run(payload):
    conn = sqlite3.connect(":memory:")
    conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 65_536)
    conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65_536)
    conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 128)
    try:
        build_fixture(conn, payload["fixture"])
        conn.execute("PRAGMA query_only=ON")
        blocked = []
        tables = set(payload["fixture"]["schemas"])

        def authorize(action, arg1, arg2, database, trigger):
            allowed = action == sqlite3.SQLITE_SELECT
            if action == sqlite3.SQLITE_READ:
                # COUNT(*) is reported by SQLite as READ(table, '', None).
                allowed = arg1 in tables and (database == "main" or (database is None and arg2 == ""))
            elif action == sqlite3.SQLITE_FUNCTION:
                allowed = (arg2 or "").lower() in FUNCTIONS
            if not allowed:
                blocked.append(action)
            return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY

        conn.set_authorizer(authorize)
        ticks = [0]

        def progress():
            ticks[0] += 1
            return int(ticks[0] > 1000)

        conn.set_progress_handler(progress, 1000)
        try:
            cursor = conn.execute(payload["sql"])
            if cursor.description is None:
                return response("unsupported", "select_required")
            names = [item[0] for item in cursor.description]
            if len(set(names)) != len(names):
                return response("unsupported", "duplicate_column_names")
            rows = cursor.fetchmany(201)
            if len(rows) > 200:
                return response("unsupported", "result_row_limit")
            columns = []
            for index, name in enumerate(names):
                values = [row[index] for row in rows if row[index] is not None]
                if not values:
                    return response("unsupported", "unknown_result_type")
                kinds = {type(value) for value in values}
                if len(kinds) != 1 or next(iter(kinds)) not in {int, float, str}:
                    return response("unsupported", "heterogeneous_result_type")
                if any(type(value) is float and not math.isfinite(value) for value in values):
                    return response("unsupported", "nonfinite_result")
                kind = {int: "int", float: "float", str: "str"}[next(iter(kinds))]
                columns.append({"name": name, "kind": kind,
                                "nullable": any(row[index] is None for row in rows)})
            result = response("executed", actual={"columns": columns, "rows": rows})
            if len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode()) > 900_000:
                return response("unsupported", "output_limit")
            return result
        except sqlite3.Error as exc:
            if blocked:
                return response("unsupported", "sql_not_allowed")
            if "no such function:" in str(exc).lower() or "no such module:" in str(exc).lower():
                return response("unsupported", "sql_not_allowed")
            if ticks[0] > 1000:
                return response("timeout", "instruction_limit")
            return response("error", "sql_execution_error")
    finally:
        conn.close()


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024**2, 256 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1_000_000, 1_000_000))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        raw = sys.stdin.buffer.read(1_000_001)
        if len(raw) > 1_000_000:
            result = response("unsupported", "input_limit")
        else:
            result = run(json.loads(raw))
    except (ValueError, TypeError, KeyError, OverflowError, sqlite3.Error):
        result = response("unsupported", "invalid_fixture")
    except MemoryError:
        result = response("unsupported", "memory_limit")
    sys.stdout.write(json.dumps(result, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
