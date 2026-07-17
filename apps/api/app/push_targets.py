"""Server-side validation for client-supplied Web Push endpoint URLs.

The push dispatcher (``services/notify._deliver_push``) POSTs to whatever
``endpoint`` we have stored, via pywebpush, from inside the VPC-egress Lambda.
An attacker who could register an arbitrary endpoint would therefore turn our
push fan-out into an SSRF primitive — reaching the instance metadata service
(169.254.169.254), internal/private hosts, etc. We constrain endpoints to the
handful of real Web Push service origins, and defensively reject IP-literal
hosts in loopback/link-local/private/reserved ranges.

Trade-off: we do NOT resolve DNS names here. A blocking lookup in the request
path adds latency and opens a TOCTOU gap (the name could re-resolve to a
private IP between validation and the actual send). We rely on the origin
allowlist for DNS names, and on network egress controls at deploy time.
"""

import ipaddress
from urllib.parse import urlsplit

# Known Web Push service host suffixes. An endpoint host must equal one of
# these exactly or end with "." + suffix. Covers the required origins:
#   fcm.googleapis.com / *.googleapis.com   (Chrome / Chromium — FCM)
#   *.push.services.mozilla.com             (Firefox)
#   *.notify.windows.com                    (Edge / Windows)
#   web.push.apple.com / *.push.apple.com   (Safari)
# Extend this tuple to onboard a new browser vendor's push host.
ALLOWED_PUSH_HOST_SUFFIXES: tuple[str, ...] = (
    "googleapis.com",
    "push.services.mozilla.com",
    "notify.windows.com",
    "push.apple.com",
)


def _host_allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in ALLOWED_PUSH_HOST_SUFFIXES
    )


def validate_push_endpoint(endpoint: str) -> str:
    """Return ``endpoint`` unchanged if it is a plausible Web Push URL, else
    raise ValueError. Enforced: https scheme, host on the provider allowlist,
    and (defense in depth) IP-literal hosts are rejected outright — with a
    clear signal for the loopback/private/link-local/reserved ranges that make
    SSRF interesting."""
    parts = urlsplit(endpoint)
    if parts.scheme != "https":
        raise ValueError("Push endpoint must use https")
    host = parts.hostname
    if not host:
        raise ValueError("Push endpoint has no host")
    # An IP literal is never a real push service. Reject all of them; call out
    # the private/reserved ranges explicitly since those are the SSRF targets.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_private
            or ip.is_reserved
            or not ip.is_global
        ):
            raise ValueError(
                "Push endpoint host is a private or reserved address"
            )
        raise ValueError("Push endpoint host must be a known push service, not an IP")
    if not _host_allowed(host):
        raise ValueError("Push endpoint host is not a recognized push service")
    return endpoint
