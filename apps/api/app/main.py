import logging

import stripe
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings

logger = logging.getLogger(__name__)
from .routers import (
    admin,
    auth,
    calls,
    capsules,
    children,
    contributions,
    erasure,
    families,
    feed,
    funds,
    goals,
    invites,
    issues,
    legacy,
    me,
    predictions,
    premium,
    social,
    vault,
    webhooks,
)

app = FastAPI(title="FutureRoots API", version="0.1.0")


@app.exception_handler(stripe.error.StripeError)
def _stripe_error_handler(request: Request, exc: stripe.error.StripeError) -> JSONResponse:
    """A Stripe call failed in a request path (e.g. Connect account creation,
    Checkout). Domain routers stay Stripe-agnostic, so translate any uncaught
    Stripe error into a warm, honest 503 here rather than leaking a 500. The
    full error is logged for operators; users never see Stripe internals.
    Signature-verification errors are caught in the webhook router and never
    reach this handler."""
    logger.error("Uncaught Stripe error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "We couldn't finish that with our payments partner just "
            "now. Please try again in a few minutes."
        },
    )

_origins = {settings.web_base_url, "http://localhost:3000"}
_origins.update(o.strip() for o in settings.cors_extra_origins.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(families.router)
app.include_router(children.router)
app.include_router(invites.router)
app.include_router(vault.router)
app.include_router(feed.router)
app.include_router(goals.router)
app.include_router(contributions.router)
app.include_router(funds.router)
app.include_router(capsules.router)
app.include_router(predictions.router)
app.include_router(legacy.router)
app.include_router(social.router)
app.include_router(premium.router)
app.include_router(calls.router)
app.include_router(me.router)
app.include_router(erasure.router)
app.include_router(webhooks.router)
app.include_router(issues.router)
app.include_router(admin.router)

if settings.testnet_mode:
    # The wall (docs/testnet.md): the gamified testing harness exists only on
    # testnet deployments. Its routes also 404 at request time if the flag is
    # off, so the family product never exposes them.
    from .testnet.router import router as testnet_router

    app.include_router(testnet_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
