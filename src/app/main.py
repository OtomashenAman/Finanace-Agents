from fastapi import FastAPI

app = FastAPI(title="Finance Agent Command Center")


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "FinanceACC API is running"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
