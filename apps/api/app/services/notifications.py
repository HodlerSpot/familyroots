"""Notification-preference defaults.

A missing NotificationPreference row means the product defaults below. This is
the one source of truth for "what a user who has never touched their settings
gets"; it mirrors the column defaults on NotificationPreference (which only
apply on flush) and is consumed by services.notify (gating) and routers.me
(the settings screen).

The historical per-family email fan-out (notify_members) has been retired: all
family notifications now flow through services.notify.notify(), which writes an
always-on bell row plus pref-gated email and web push. See services/notify.py
for the taxonomy and dispatch rules.
"""

# Defaults for a user who has never touched their preferences. 20 switches:
# ten kinds across Email + Push. Keep in lockstep with the column defaults on
# models.NotificationPreference.
DEFAULT_PREFS = {
    # original four email kinds (values unchanged)
    "email_new_member": True,
    "email_milestone": True,
    "email_memory": False,
    "email_legacy": False,
    # push mirrors of the original four (mirror the email defaults)
    "push_new_member": True,
    "push_milestone": True,
    "push_memory": False,
    "push_legacy": False,
    # six new kinds, both channels
    "email_call_live": False,
    "push_call_live": True,
    "email_contribution": True,
    "push_contribution": True,
    "email_fund_activated": True,
    "push_fund_activated": True,
    "email_capsule_sealed": False,
    "push_capsule_sealed": True,
    "email_capsule_released": True,
    "push_capsule_released": True,
    "email_announcements": True,
    "push_announcements": True,
}
