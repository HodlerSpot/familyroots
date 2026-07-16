"""FutureRoots Premium lifecycle email copy — all strings in one place.

Copy source of truth: docs/brand/premium-copy.md (final, brand-guardian owned).
Every string here is pasted from that deck; edit the deck first, then mirror
changes here. Builders return {"subject", "body", "html"} for
EmailSender.send(to=..., **payload).

Premium emails are transactional (not preference-gated — a payment failure
must reach the owner) and are sent to computed audiences (owner-only /
parents-only) by services/premium.py, never through notify_members.
"""

from datetime import datetime

from ..config import settings
from .email_templates import render_email
from .text import family_phrase


def _date(dt: datetime) -> str:
    """Long-form date per the copy deck: 'March 12, 2027'."""
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def _amount(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def family_url(family_id) -> str:
    return f"{settings.web_base_url}/family/{family_id}"


def plan_section_url(family_id) -> str:
    """Deep link to the Plan section of family settings."""
    return f"{family_url(family_id)}#plan"


def premium_page_url(family_id) -> str:
    return f"{family_url(family_id)}/premium"


def moments_url(family_id) -> str:
    return f"{family_url(family_id)}/moments"


def _build(
    *,
    subject: str,
    preheader: str,
    greeting: str,
    paragraphs: list[str],
    highlight: str | None = None,
    cta_label: str | None = None,
    cta_url: str | None = None,
    secondary_label: str | None = None,
    secondary_url: str | None = None,
    footnote: str | None = None,
) -> dict:
    lines: list[str] = [greeting, ""]
    for p in paragraphs:
        lines += [p, ""]
    if highlight:
        lines += ["  " + highlight.replace("\n", "\n  "), ""]
    if cta_label and cta_url:
        lines += [f"{cta_label}: {cta_url}", ""]
    if secondary_label and secondary_url:
        lines += [f"{secondary_label}: {secondary_url}", ""]
    if footnote:
        lines += [footnote, ""]
    lines += ["With warmth,", "The FutureRoots team"]
    return {
        "subject": subject,
        "body": "\n".join(lines),
        "html": render_email(
            preheader=preheader,
            greeting=greeting,
            paragraphs=paragraphs,
            highlight=highlight,
            cta_label=cta_label,
            cta_url=cta_url,
            secondary_label=secondary_label,
            secondary_url=secondary_url,
            footnote=footnote,
        ),
    }


# --- 2.1 Premium activated — to all active parents ---

def premium_activated(
    *, parent_name: str, plan: str, renewal_date: datetime, family_id
) -> dict:
    price_line = (
        f"Your plan is $9.99 a month and renews automatically on "
        f"{_date(renewal_date)}. You can cancel anytime from your family's "
        f"Plan settings, no questions asked."
        if plan == "monthly"
        else f"Your plan is $99 a year and renews automatically on "
        f"{_date(renewal_date)}. You can cancel anytime from your family's "
        f"Plan settings, no questions asked."
    )
    return _build(
        subject="Welcome to FutureRoots Premium",
        preheader="Video memories and family video calls are on for the whole family.",
        greeting=f"Hi {parent_name},",
        paragraphs=[
            "Your family is now on FutureRoots Premium. Video memories and "
            "family video calls are ready for everyone, starting right now.",
            price_line,
            "A lovely first step: share a video the whole family will smile at.",
        ],
        cta_label="Share your first video",
        cta_url=moments_url(family_id),
        secondary_label="Manage your plan",
        secondary_url=plan_section_url(family_id),
        footnote="This email confirms your subscription. Receipts and payment "
        "details live in your family's Plan settings.",
    )


# --- 2.2 Gift confirmation — to the gifter (doubles as receipt) ---

def gift_confirmation(
    *,
    gifter_name: str,
    family_name: str,
    amount_cents: int,
    payment_date: datetime,
    starts_at: datetime,
    ends_at: datetime,
    family_id,
) -> dict:
    # Use the shared phrasing helper so a name like "The Free Family" doesn't
    # render as "the The Free Family family".
    family = family_phrase(family_name)
    return _build(
        subject=f"Your gift to {family} is live",
        preheader="A year of FutureRoots Premium, from you. Thank you.",
        greeting=f"Hi {gifter_name},",
        paragraphs=[
            f"What a lovely thing to do. Your gift of one year of FutureRoots "
            f"Premium is now live for {family}, and they know "
            f"it came from you.",
            "All year long, the family can save video memories and gather for "
            "family video calls.",
            "This was a one-time payment. Nothing renews, and no one will ever "
            "be charged when the year ends.",
        ],
        highlight=(
            f"One year of FutureRoots Premium for {family}\n"
            f"{_amount(amount_cents)}, paid once on {_date(payment_date)}\n"
            f"Coverage: {_date(starts_at)} to {_date(ends_at)}"
        ),
        cta_label="Visit the family feed",
        cta_url=family_url(family_id),
        footnote="Keep this email as your receipt.",
    )


# --- 2.3 Gift received — to all active parents ---

def gift_received(
    *,
    parent_name: str,
    gifter_name: str,
    ends_at: datetime,
    message: str | None,
    has_active_subscription: bool,
    combined_end: datetime | None,
    family_id,
) -> dict:
    paragraphs = [
        f"Wonderful news: {gifter_name} just gave your family a full year of "
        f"FutureRoots Premium. Video memories and family video calls are on "
        f"for everyone, through {_date(ends_at)}.",
        "The gift is fully paid. It will never charge you, and it doesn't "
        "renew. When it ends, your family simply returns to the Free plan, "
        "and everything you've saved stays yours.",
    ]
    if has_active_subscription and combined_end is not None:
        paragraphs.append(
            f"Since your family already has a Premium plan, the gift stacks on "
            f"after it, so you're covered through {_date(combined_end)}. If "
            f"you'd like, you can turn off your own renewal and let the gift "
            f"carry you. You'll find that option in your family's Plan settings."
        )
    return _build(
        subject=f"{gifter_name} gave your family a year of Premium",
        preheader=f"Twelve months of video memories and family calls, with "
        f"love from {gifter_name}.",
        greeting=f"Hi {parent_name},",
        paragraphs=paragraphs,
        highlight=(f"“{message}”\n{gifter_name}" if message else None),
        cta_label="See it on the family feed",
        cta_url=family_url(family_id),
    )


# --- 2.4 Payment failed — to the subscription owner only ---

def payment_failed(*, owner_name: str, amount_cents: int, family_id) -> dict:
    return _build(
        subject="A quick note about your Premium payment",
        preheader="We'll retry automatically. Premium stays on for your family.",
        greeting=f"Hi {owner_name},",
        paragraphs=[
            f"Your family's Premium payment of {_amount(amount_cents)} didn't "
            f"go through this time. This happens: cards expire, banks get "
            f"cautious. It's easy to sort out.",
            "Nothing changes for your family right now. Premium stays fully "
            "on, and we'll retry the payment automatically over the next few "
            "days.",
            "If your card has changed, you can update it in a minute on our "
            "secure billing page.",
        ],
        cta_label="Update payment details",
        cta_url=plan_section_url(family_id),
        footnote="If a retry goes through, you're all set and can safely "
        "ignore this email. We'll only write again if we still need you.",
    )


# --- 2.5 Premium ended — to owner + all active parents ---

def premium_ended(*, parent_name: str, family_id) -> dict:
    return _build(
        subject="Your family is back on the Free plan",
        preheader="Every photo, video, and memory is exactly where you left it.",
        greeting=f"Hi {parent_name},",
        paragraphs=[
            "Your family's time on FutureRoots Premium has ended, and you're "
            "now on the Free plan.",
            "First, the important part: everything you've saved stays yours. "
            "Every photo, milestone, contribution, and memory is safe, and "
            "every video you've already shared will always play and download "
            "just as before.",
            "The Free plan still holds everything at the heart of FutureRoots: "
            "the family feed, photos and voice notes, milestones, "
            "contributions, goals, time capsules, and the family archive. Only "
            "new video uploads and family video calls wait for Premium.",
            "Whenever you'd like those back, Premium is a minute away.",
        ],
        cta_label="Return to Premium",
        cta_url=premium_page_url(family_id),
    )


# --- 2.6 Cancellation confirmed — to owner (+ other parents, same copy) ---

def cancellation_confirmed(*, parent_name: str, end_date: datetime, family_id) -> dict:
    return _build(
        subject=f"Premium stays on until {_date(end_date)}",
        preheader="Auto-renewal is off. Nothing else changes until then.",
        greeting=f"Hi {parent_name},",
        paragraphs=[
            f"As requested, your family's Premium plan is set to end on "
            f"{_date(end_date)}. You won't be charged again.",
            f"Until then, nothing changes: videos, family calls, everything "
            f"stays on. After {_date(end_date)} your family moves to the Free "
            f"plan, and everything you've saved stays yours.",
            f"If you change your mind before {_date(end_date)}, you can resume "
            f"with one tap. No new checkout, no interruption.",
        ],
        cta_label="Resume Premium",
        cta_url=plan_section_url(family_id),
        footnote="This change was made from your family's Plan settings. Any "
        "parent in the family can manage the plan.",
    )


# --- 2.7 Annual renewal reminder — to owner (annual only) ---
# Lead time is NOT set here: it's Stripe Billing's `invoice.upcoming` window
# (see docs/deploy.md — must be 30 days for CA ARL, within the 15-45 day
# window). The copy deliberately asserts no specific day count so it stays
# correct whatever that window is; it names only the renewal date.

def renewal_upcoming(*, owner_name: str, renewal_date: datetime, family_id) -> dict:
    return _build(
        subject=f"Your FutureRoots Premium renews on {_date(renewal_date)}",
        preheader="$99 for another year of family videos and calls. Nothing to "
        "do if that sounds right.",
        greeting=f"Hi {owner_name},",
        paragraphs=[
            f"A friendly heads-up: your family's annual Premium plan renews on "
            f"{_date(renewal_date)} for $99.",
            "If you'd like to keep going, there's nothing to do. Video "
            "memories and family video calls continue without interruption.",
            f"If you'd rather not renew, you can cancel anytime before "
            f"{_date(renewal_date)} from your family's Plan settings. Your "
            f"family keeps Premium until then, and everything you've saved "
            f"stays yours either way.",
        ],
        cta_label="Manage your plan",
        cta_url=plan_section_url(family_id),
    )


# --- 2.8 Gift ending soon — to all active parents ---
# CASL discipline: recipients never opted into marketing and this email has no
# unsubscribe, so it must stay purely transactional — a service notice about a
# change to their account. State the facts (coverage ends on {date}, everything
# saved stays theirs, the family returns to the Free plan) with NO pricing, NO
# upsell, and a CTA that goes to their own Plan settings, not a purchase page.

def gift_ending_soon(
    *, parent_name: str, gifter_name: str, end_date: datetime, family_id
) -> dict:
    return _build(
        subject=f"{gifter_name}'s gift of Premium ends on {_date(end_date)}",
        preheader="A heads-up about your family's plan. Everything you've "
        "saved stays yours.",
        greeting=f"Hi {parent_name},",
        paragraphs=[
            f"The year of FutureRoots Premium that {gifter_name} gave your "
            f"family ends on {_date(end_date)}. What a year of memories it has "
            f"held.",
            "When the gift ends, your family simply returns to the Free plan. "
            "Everything you've saved stays yours, including every video, and "
            "it will always play and download just as before.",
            "There's nothing you need to do. This is just a heads-up so the "
            "change never takes you by surprise.",
        ],
        cta_label="See your family's plan",
        cta_url=plan_section_url(family_id),
    )


# --- Appendix A: double-subscribe apology ---

def double_subscribe_apology(
    *, parent_name: str, amount_cents: int, family_id
) -> dict:
    return _build(
        subject="One Premium plan was plenty (you weren't charged twice)",
        preheader="Two of you upgraded at the same moment. We've tidied it up.",
        greeting=f"Hi {parent_name},",
        paragraphs=[
            "Great minds: another parent upgraded your family at the same "
            "moment you did. A family only ever needs one Premium plan, so we "
            "cancelled the second one and refunded your payment in full.",
            f"Your family is fully on Premium, and there's nothing you need to "
            f"do. The refund of {_amount(amount_cents)} will appear on your "
            f"card within a few business days.",
        ],
        cta_label="See your family's plan",
        cta_url=plan_section_url(family_id),
    )


# --- Appendix B: owner departure — to remaining parents ---

def owner_departure(
    *, parent_name: str, owner_name: str, end_date: datetime, family_id
) -> dict:
    return _build(
        subject=f"Premium stays on until {_date(end_date)}",
        preheader="The plan won't renew. Resubscribe anytime, in about a minute.",
        greeting=f"Hi {parent_name},",
        paragraphs=[
            f"{owner_name}, who managed your family's Premium plan, is no "
            f"longer part of the family on FutureRoots, so the plan won't "
            f"renew.",
            f"Premium stays fully on until {_date(end_date)}. After that your "
            f"family moves to the Free plan, and everything you've saved stays "
            f"yours, including every video.",
            "Any parent can restart Premium anytime. It takes about a minute.",
        ],
        cta_label="Manage your plan",
        cta_url=plan_section_url(family_id),
    )
