from fastapi import FastAPI

app = FastAPI()


@app.get("/orders")
def status():
    return {"status": "available", "service": "Status"}
