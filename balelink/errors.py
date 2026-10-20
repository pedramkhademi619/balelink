"""Every error balelink raises.

Each has a stable ``code`` string, so a caller (or the HTTP gateway) can branch
on it without parsing messages. None carries text taken from Bale itself.
"""

from __future__ import annotations


class BaleError(Exception):
    """Base class for everything this library raises."""

    code = "ERROR"

    def __init__(self, message: str | None = None) -> None:
        text = message or (self.__class__.__doc__ or self.code).strip()
        super().__init__(text)
        self.message = text


# ---- signing in ---------------------------------------------------------------


class AuthError(BaleError):
    """Signing in did not work."""

    code = "AUTH_ERROR"


class InvalidPhone(AuthError):
    """That is not a valid phone number."""

    code = "INVALID_PHONE"


class NumberBanned(AuthError):
    """Bale refused this phone number."""

    code = "NUMBER_BANNED"


class NotRegistered(AuthError):
    """This number has no Bale account; sign up in the Bale app first."""

    code = "PHONE_NOT_REGISTERED"


class RateLimited(AuthError):
    """Too many attempts; try again in a while."""

    code = "RATE_LIMITED"


class CodeNotRequested(AuthError):
    """Ask for a code (request_code) before signing in."""

    code = "CODE_NOT_REQUESTED"


class WrongCode(AuthError):
    """The code is not right."""

    code = "WRONG_CODE"


class PasswordRequired(AuthError):
    """This account has a two-step password; pass it as ``password``."""

    code = "PASSWORD_REQUIRED"


class WrongPassword(AuthError):
    """The two-step password is wrong."""

    code = "WRONG_PASSWORD"


class NotLoggedIn(AuthError):
    """There is no saved login for this session; log in first."""

    code = "NOT_LOGGED_IN"


class AlreadyLoggedIn(AuthError):
    """This session is already logged in."""

    code = "ALREADY_LOGGED_IN"


# ---- everything after ----------------------------------------------------------


class NotConnected(BaleError):
    """The client is not connected; call start() (or use ``async with``)."""

    code = "NOT_CONNECTED"


class ConnectionFailed(BaleError):
    """Could not connect to Bale."""

    code = "CONNECTION_FAILED"


class RequestFailed(BaleError):
    """Bale did not complete the request."""

    code = "REQUEST_FAILED"


class ChatNotFound(BaleError):
    """No chat or user could be found for that."""

    code = "CHAT_NOT_FOUND"


class UnsupportedFile(BaleError):
    """That kind of file can't be sent that way."""

    code = "UNSUPPORTED_FILE"
