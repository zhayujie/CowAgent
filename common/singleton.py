import threading


def singleton(cls):
    instances = {}
    # Reentrant: a constructor that reaches its own class again must not deadlock.
    initialization_lock = threading.RLock()

    def get_instance(*args, **kwargs):
        if cls not in instances:
            with initialization_lock:
                if cls not in instances:
                    instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    # Expose the undecorated class so callers that legitimately need more than
    # one instance (e.g. running several instances of the same channel type,
    # each with its own credentials) can bypass the process-wide cache. Legacy
    # callers keep going through get_instance() and still get the singleton.
    get_instance.__wrapped__ = cls

    def new_instance(*args, **kwargs):
        """Build a fresh, uncached instance of the wrapped class."""
        return cls(*args, **kwargs)

    get_instance.new_instance = new_instance
    # The instance if one was made, without making it.
    get_instance.peek = lambda: instances.get(cls)

    return get_instance
