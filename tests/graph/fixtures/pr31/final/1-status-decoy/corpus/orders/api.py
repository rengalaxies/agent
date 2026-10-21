from fastapi import FastAPI

app = FastAPI()


@app.get("/orders")
def list_orders(day: str, cursor: str | None = None, page_size: int | None = None):
    items, next_cursor = store.read_orders(day, cursor, page_size)
    return {"items": items, "next_cursor": next_cursor}
