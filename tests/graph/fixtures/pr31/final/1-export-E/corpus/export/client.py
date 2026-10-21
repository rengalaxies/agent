import requests as http

BASE_URL = "https://orders.test"


def load_day(day):
    items, cursor = [], None
    while True:
        response = http.get(BASE_URL + "/orders", params={"day": day, "cursor": cursor}, timeout=10)
        response.raise_for_status()
        page = response.json()
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return items
