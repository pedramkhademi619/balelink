"""An HTTP gateway around ``BaleClient`` - run Bale accounts as a service.

    pip install "balesdk[gateway]"
    BALESDK_API_KEY=secret balesdk serve

Any language can then log in, send and receive (by webhook) over plain HTTP,
the way WAHA does for WhatsApp. See the README for the endpoints.
"""

from .app import create_app
from .config import Settings

__all__ = ["Settings", "create_app"]
