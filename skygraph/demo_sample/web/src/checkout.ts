import { placeOrder } from "./api";

export class Checkout {
  async submit(productId: number, quantity: number) {
    if (quantity < 1) {
      throw new Error("nothing to order");
    }
    return placeOrder(productId, quantity);
  }
}
