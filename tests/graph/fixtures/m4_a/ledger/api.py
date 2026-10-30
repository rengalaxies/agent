from fastapi import FastAPI

app = FastAPI()


@app.get("/parcels")
def parcels(page_size: int = 40):
    return {"items": ["unrelated-ledger-entry"]}
