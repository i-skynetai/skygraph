from fastapi import FastAPI
from app.models import User
from app.repo import find_user

app = FastAPI()


@app.post("/users")
def create_user(email: str):
    return User(email=email)


@app.get("/users/{user_id}")
def read_user(user_id: int):
    return find_user(user_id)
