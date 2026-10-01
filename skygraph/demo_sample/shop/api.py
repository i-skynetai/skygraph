"""The HTTP API."""
from fastapi import FastAPI

from shop.models import Order
from shop.orders import OrderService

app = FastAPI()


@app.post("/orders")
def create_order(product_id: int, quantity: int) -> Order:
    """Place an order: record it, then let the service reserve the stock."""
    order = Order(product_id=product_id, quantity=quantity)
    OrderService().place(order)
    return order


@app.get("/orders/{order_id}")
def read_order(order_id: int) -> Order:
    return OrderService().find(order_id)
