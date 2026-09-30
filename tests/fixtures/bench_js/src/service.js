import { Repo } from "./repo.js";

export class Service {
  constructor() {
    this.repo = new Repo();
  }

  handle(name) {
    return this.repo.save(name);
  }
}
