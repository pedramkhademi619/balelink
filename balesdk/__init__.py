"""balesdk - log in to Bale (بله) as yourself, send and receive messages.

    from balesdk import BaleClient, filters as F

See the README. Unofficial; not affiliated with Bale.
"""

from . import filters
from .client import BaleClient
from .errors import (
    AlreadyLoggedIn,
    AuthError,
    BaleError,
    ChatNotFound,
    CodeNotRequested,
    ConnectionFailed,
    InvalidPhone,
    NotConnected,
    NotLoggedIn,
    NotRegistered,
    NumberBanned,
    PasswordRequired,
    RateLimited,
    RequestFailed,
    UnsupportedFile,
    WrongCode,
    WrongPassword,
)
from .models import (
    Attachment,
    Chat,
    ChatKind,
    CodeRequest,
    FileKind,
    Me,
    Message,
    User,
)
from .phone import is_plausible_phone, normalize_phone
from .store import SessionStore
from .text import split_text

__version__ = "0.1.0"

__all__ = [
    "BaleClient",
    "filters",
    "Message",
    "Chat",
    "ChatKind",
    "User",
    "Me",
    "Attachment",
    "CodeRequest",
    "FileKind",
    "SessionStore",
    "split_text",
    "normalize_phone",
    "is_plausible_phone",
    "BaleError",
    "AuthError",
    "InvalidPhone",
    "NumberBanned",
    "NotRegistered",
    "RateLimited",
    "CodeNotRequested",
    "WrongCode",
    "PasswordRequired",
    "WrongPassword",
    "NotLoggedIn",
    "AlreadyLoggedIn",
    "NotConnected",
    "ConnectionFailed",
    "RequestFailed",
    "ChatNotFound",
    "UnsupportedFile",
]
