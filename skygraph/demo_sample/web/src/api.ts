// The browser's side of the API.
export async function placeOrder(productId: number, quantity: number) {
  const response = await fetch("/orders", {
    method: "POST",
    body: JSON.stringify({ productId, quantity }),
  });
  return response.json();
}
