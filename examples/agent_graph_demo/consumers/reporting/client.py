import requests


def run():
    response = requests.get("http://orders:8000/orders", timeout=5)
    response.raise_for_status()
    return [item["id"] for item in response.json()["items"]]
