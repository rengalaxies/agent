"""Author-written acceptance application, not customer data."""
from fastapi import FastAPI

app = FastAPI()


@app.get("/orders")
def list_orders(day: str, page_size: int = 100):
    rows = [{"id": i, "day": day} for i in range(1, 61)]
    return {"items": rows[:page_size]}
