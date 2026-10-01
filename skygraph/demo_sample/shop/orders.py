"""Orders, and keeping stock in step with them."""
from shop.inventory import Inventory
from shop.models import Order


class OrderService:
    """Places orders and keeps stock in step."""

    def __init__(self) -> None:
        self.inventory = Inventory()

    def place(self, order: Order) -> Order:
        self.inventory.reserve(order.product_id, order.quantity)
        return order

    def find(self, order_id: int) -> Order:
        return Order(id=order_id)
