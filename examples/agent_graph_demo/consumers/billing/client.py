import requests


def run():
    result = []
    cursor = 0
    for _ in range(10):
        response = requests.get(
            "http://orders:8000/orders", params={"cursor": cursor}, timeout=5
        )
        response.raise_for_status()
        page = response.json()
        result.extend(item["id"] for item in page["items"])
        next_cursor = page["next_cursor"]
        if next_cursor is None:
            return result
        if not isinstance(next_cursor, int) or next_cursor <= cursor:
            raise ValueError("non_advancing_cursor")
        cursor = next_cursor
    raise ValueError("pagination_limit")
