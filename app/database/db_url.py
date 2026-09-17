"""Turn a PaaS ``DATABASE_URL`` into something asyncpg can actually open.

Fly.io, Heroku, Supabase and friends hand out connection strings that carry libpq query
parameters (``?sslmode=disable``, sometimes plus ``sslrootcert=``).  SQLAlchemy forwards
*every* URL query parameter as a keyword argument of the DB-API ``connect()``, and
``asyncpg.connect()`` understands ``ssl`` but has no ``sslmode`` - so the first connection
dies with::

    TypeError: connect() got an unexpected keyword argument 'sslmode'

On Fly.io that happens inside the ``alembic upgrade head`` release command, i.e. before the
bot ever starts polling.  ``prepare_database_url()`` moves those parameters out of the URL and
into ``connect_args``, with the semantics libpq documents:

``disable`` / ``allow`` / ``prefer``  no TLS (``ssl=False``)
``require``                           TLS, server certificate *not* verified
``verify-ca``                         TLS + CA verification (``sslrootcert`` honoured)
``verify-full``                       TLS + CA verification + hostname check
anything else                         TLS, like ``require``, plus a warning

An :class:`ssl.SSLContext` is built explicitly instead of relying on asyncpg's newer string
values for ``ssl``, so this behaves identically on every asyncpg version we support.
"""

from __future__ import annotations

import logging
import ssl
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

__all__ = ["prepare_database_url"]

logger = logging.getLogger(__name__)

_CERT_KEYS = ("sslrootcert", "sslcert", "sslkey", "sslcrl", "sslpassword")
_SSL_KEYS = frozenset(("ssl", "sslmode", *_CERT_KEYS))
_PLAIN_MODES = frozenset({"disable", "allow", "prefer"})
_VERIFIED_MODES = frozenset({"verify-ca", "verify-full"})
_VERIFIED_HOST_MODES = frozenset({"verify-full"})


def _ssl_context(mode: str, certs: dict[str, str]) -> ssl.SSLContext:
    root = certs.get("sslrootcert")
    if not root:
        context = ssl.create_default_context()
    else:
        try:
            context = ssl.create_default_context(cafile=root)
        except OSError as exc:  # the path comes from a URL, so name it in the message
            raise OSError(
                f"sslrootcert={root!r} from DATABASE_URL cannot be read ({exc}); it must exist "
                "inside the container - `fly postgres attach` writes it there only when TLS is "
                "enabled, so `sslmode=require` or `sslmode=disable` is what a private-network "
                "database should use."
            ) from exc
    if mode not in _VERIFIED_MODES:
        # `require`: encrypt, but do not validate the certificate (libpq semantics).
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    else:
        context.check_hostname = mode in _VERIFIED_HOST_MODES
    client_cert = certs.get("sslcert")
    if client_cert:
        context.load_cert_chain(client_cert, certs.get("sslkey"))
    return context


def prepare_database_url(url: str) -> tuple[str, dict[str, Any]]:
    """Split ``url`` into an asyncpg-friendly URL and the matching ``connect_args``.

    Returns the URL unchanged (and no arguments) for SQLite and for URLs without libpq SSL
    parameters, so the common local case pays nothing for this.
    """
    if "+asyncpg" not in url or not any(key in url for key in _SSL_KEYS):
        return url, {}

    parts = urlsplit(url)
    mode = ""
    certs: dict[str, str] = {}
    kept: list[str] = []
    for segment in parts.query.split("&"):
        if not segment:
            continue
        key, _, raw_value = segment.partition("=")
        lowered = key.lower()
        value = unquote(raw_value)
        if lowered in ("ssl", "sslmode"):
            mode = value.strip().lower()
        elif lowered in _CERT_KEYS:
            if value:
                certs[lowered] = value
        else:
            # kept verbatim: re-encoding would corrupt values such as `options=-c%20timezone`
            kept.append(segment)

    if not (mode or certs):
        return url, {}

    if mode and mode not in (_PLAIN_MODES | _VERIFIED_MODES | {"require"}):
        logger.warning(
            "unknown sslmode %r in DATABASE_URL; encrypting without certificate verification", mode
        )

    if mode in _PLAIN_MODES:
        connect_args: dict[str, Any] = {"ssl": False}
    else:  # require / verify-* / unknown / only certificates
        connect_args = {"ssl": _ssl_context(mode, certs)}

    query = "&".join(kept)
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    logger.info(
        "translated libpq SSL parameters for asyncpg",
        extra={"sslmode": mode or "implied by ssl* parameters", "remaining_params": len(kept)},
    )
    return clean, connect_args
