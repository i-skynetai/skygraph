import os
from app.repo import Registry, find_user


def configure(config):
    url = os.environ["DATABASE_URL"]
    return config.get("a"), url


def use(reg):
    return reg.register(1)


class Worker:
    def run(self):
        self.step()
        return find_user(1)

    def step(self):
        return Registry()
