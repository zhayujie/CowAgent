import inspect
from typing import Any


def websocket_app_run_forever(ws: Any, **kwargs: Any) -> None:
    """
    Call WebSocketApp.run_forever; strip reconnect= if the installed
    websocket-client is too old (reconnect was added in a later 1.x release).
    """
    if "reconnect" in kwargs:
        try:
            params = inspect.signature(ws.run_forever).parameters
        except (TypeError, ValueError):
            params = {}
        if "reconnect" not in params:
            kwargs = {k: v for k, v in kwargs.items() if k != "reconnect"}
    ws.run_forever(**kwargs)
