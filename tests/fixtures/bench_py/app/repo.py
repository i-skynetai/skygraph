from app.models import User


def find_user(user_id):
    return User(id=user_id)


def get(key):
    """A top-level `get` — bait for anything that resolves `x.get()` by name."""
    return key


class Registry:
    def register(self, item):
        return item

    def get(self, key):
        return key
