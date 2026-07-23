"""Platform-aware Stripe / Connect return URLs (mobile deep-link bridge).

Web (the default — ``X-Client-Platform`` absent or ``web``) keeps the exact same
hosted return pages it has always used. Callers must leave those branches
byte-for-byte unchanged.

For the native app there is one extra hop: hosted Stripe Checkout, the Billing
Portal, and Connect onboarding all live in an in-app browser and can only
redirect to an https URL (Stripe rejects custom schemes). So a mobile request
gets return URLs pointing at a tiny https bridge page on ``web_base_url``
(``/m/return``), which immediately deep-links back into the app via the
``futureroots://`` scheme and shows a warm fallback if the app doesn't open.

The ``to`` target tells the bridge which app screen to hand control to. The
target vocabulary is a contract shared with the web bridge page
(``apps/web/src/app/m/return/page.tsx``) and the mobile app's deep-link routes:

    premium-success   family/{family_id}/premium/success   (+ session_id)
    premium-cancel    family/{family_id}/premium
    gift-success      family/{family_id}/premium/gift/success (+ session_id)
    gift-cancel       family/{family_id}/premium/gift
    portal            family/{family_id}
    fund-return       family/{family_id}/child/{child_id}/fund/setup/return
    fund-refresh      family/{family_id}/child/{child_id}/fund/setup/refresh

``family_id`` / ``child_id`` ride along as query params so the bridge can build
the fully-qualified deep link without embedding them in the target name.
"""

from urllib.parse import urlencode

from .config import settings

MOBILE_PLATFORMS = frozenset({"ios", "android"})


def is_mobile(platform: str) -> bool:
    return platform in MOBILE_PLATFORMS


def bridge_url(to: str, **params: str | None) -> str:
    """Build the https ``/m/return`` bridge URL for a mobile return.

    ``to`` is the deep-link target; keyword params (``family_id``, ``child_id``)
    are appended as query string. ``None`` values are dropped. The Stripe
    ``{CHECKOUT_SESSION_ID}`` placeholder must NOT be passed here (urlencoding
    would break Stripe's substitution) — append it as a literal suffix instead.
    """
    query = [("to", to)]
    query.extend((key, value) for key, value in params.items() if value is not None)
    return f"{settings.web_base_url}/m/return?{urlencode(query)}"
