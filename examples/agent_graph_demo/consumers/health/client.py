import requests


def run():
    response = requests.get("http://status:8000/orders", timeout=5)
    response.raise_for_status()
    return response.json()
