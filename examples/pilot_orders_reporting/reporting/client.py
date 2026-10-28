"""Direct requests call within the supported static profile."""
import requests

BASE_URL = "https://orders.pilot.invalid"


def load_day(day):
    response = requests.get(BASE_URL + "/orders", params={"day": day}, timeout=10)
    response.raise_for_status()
    return response.json()["items"]
