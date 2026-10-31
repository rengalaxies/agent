from fastapi import FastAPI

app = FastAPI()
ROWS = tuple(range(9))


@app.get("/parcels")
def parcels(page_size: int = 40):
    return {"items": list(ROWS[:page_size])}


@app.post("/labels")
def labels():
    return {"created": True}
