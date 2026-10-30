import requests as net

HOST = "https://edge.example.test"


def load(target):
    return net.get(target).json()["items"]


def export():
    return load(HOST + "/v2/parcels")
