from requests import get as fetch


def check_inventory():
    return fetch("https://inventory.test/orders", timeout=10)
