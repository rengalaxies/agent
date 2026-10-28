import requests as net

HOST = "https://edge.example.test"


def export():
    return net.get(HOST + "/v2/parcels", params={"region": "west"}).json()["items"]
