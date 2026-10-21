import requests

BASE_URL = "https://orders.test"


def load_day(day):
    response = requests.get(BASE_URL + "/orders", params={"day": day}, timeout=10)
    response.raise_for_status()
    return response.json()["items"]
