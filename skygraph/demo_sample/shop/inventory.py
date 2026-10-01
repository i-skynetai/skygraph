"""Stock levels."""
from shop.settings import max_per_order


class Inventory:
    """Stock levels per product."""

    def reserve(self, product_id: int, quantity: int) -> None:
        """Hold `quantity` units of a product for an order."""
        if not 0 < quantity <= max_per_order():
            raise ValueError("quantity out of range")
        self._take(product_id, quantity)

    def _take(self, product_id: int, quantity: int) -> None:
        pass
