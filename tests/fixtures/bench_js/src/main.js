import { Service } from "./service.js";

export function run() {
  const s = new Service();
  return s.handle("x");
}
