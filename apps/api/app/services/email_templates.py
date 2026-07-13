"""Branded HTML email layout for every outgoing FutureRoots email.

Email clients are hostile, so the layout follows the brand's email craft
rules: a single 600px table, inline CSS only, system font stack, absolute
image URLs with alt text, and a bulletproof CTA button (a padded table cell,
never an image). The email must read fine with images blocked — the two-tone
HTML wordmark next to the logo carries the brand even then.

Every user-provided value (names, titles, messages) is HTML-escaped here;
callers pass plain strings and never markup.
"""

from html import escape

LOGO_URL = "https://futureroots.app/email-logo-v2.png"
TAGLINE = "Building Generational Wealth &amp; Memories"

# Brand palette (docs/brand): emerald primary, logo green + royal blue
# wordmark, warm stone neutrals.
EMERALD = "#047857"
LOGO_GREEN = "#1FA84D"
ROYAL_BLUE = "#1E4FD8"
BACKGROUND = "#FAFAF9"  # stone-50: warm, not clinical
CARD = "#FFFFFF"
BODY_TEXT = "#44403C"  # stone-700
MUTED = "#78716C"  # stone-500
HEADING = "#292524"  # stone-800

FONT = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def _multiline(text: str) -> str:
    """Escape user text and preserve intentional line breaks."""
    return escape(text).replace("\n", "<br>")


def _cta_button(label: str, url: str) -> str:
    """Bulletproof button: the padded, colored td is the button."""
    return (
        '<table role="presentation" align="center" cellpadding="0" cellspacing="0" '
        'border="0" style="margin:28px auto 4px auto;">'
        "<tr>"
        f'<td align="center" style="background-color:{EMERALD};border-radius:8px;">'
        f'<a href="{escape(url)}" style="display:inline-block;padding:14px 36px;'
        f"font-family:{FONT};font-size:16px;font-weight:700;line-height:1.2;"
        f'color:#FFFFFF;text-decoration:none;border-radius:8px;">{escape(label)}</a>'
        "</td></tr></table>"
    )


def _secondary_link(label: str, url: str) -> str:
    return (
        f'<p style="margin:16px 0 0 0;text-align:center;font-family:{FONT};'
        f'font-size:15px;line-height:1.6;">'
        f'<a href="{escape(url)}" style="color:{EMERALD};text-decoration:underline;">'
        f"{escape(label)}</a></p>"
    )


def render_email(
    *,
    preheader: str,
    greeting: str,
    paragraphs: list[str],
    highlight: str | None = None,
    cta_label: str | None = None,
    cta_url: str | None = None,
    secondary_label: str | None = None,
    secondary_url: str | None = None,
    footnote: str | None = None,
) -> str:
    """Render the shared branded layout.

    preheader   — inbox preview text (hidden in the body)
    greeting    — "Hi Pat," line
    paragraphs  — body copy, one string per paragraph (plain text; escaped here)
    highlight   — optional callout card (e.g. a milestone title or a quoted note)
    cta_*       — the one primary action, as an emerald button
    secondary_* — optional quieter text link under the button
    footnote    — small muted print (expiries, "safe to ignore" reassurance)
    """
    body_paragraphs = "".join(
        f'<p style="margin:0 0 16px 0;font-family:{FONT};font-size:16px;'
        f'line-height:1.6;color:{BODY_TEXT};">{_multiline(p)}</p>'
        for p in paragraphs
    )

    highlight_html = ""
    if highlight:
        highlight_html = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'border="0" style="margin:4px 0 20px 0;">'
            f'<tr><td style="background-color:{BACKGROUND};border-left:4px solid '
            f'{LOGO_GREEN};border-radius:0 8px 8px 0;padding:16px 20px;'
            f"font-family:{FONT};font-size:16px;line-height:1.6;color:{HEADING};"
            f'font-weight:600;">{_multiline(highlight)}</td></tr></table>'
        )

    cta_html = ""
    if cta_label and cta_url:
        cta_html = _cta_button(cta_label, cta_url)
    if secondary_label and secondary_url:
        cta_html += _secondary_link(secondary_label, secondary_url)

    footnote_html = ""
    if footnote:
        footnote_html = (
            f'<p style="margin:28px 0 0 0;padding-top:20px;border-top:1px solid '
            f"#E7E5E4;font-family:{FONT};font-size:13px;line-height:1.6;"
            f'color:{MUTED};">{_multiline(footnote)}</p>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FutureRoots</title>
</head>
<body style="margin:0;padding:0;background-color:{BACKGROUND};">
<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{BACKGROUND};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;">
<tr><td style="padding:0 8px 20px 8px;">
<img src="{LOGO_URL}" alt="FutureRoots" width="48" height="48" style="display:inline-block;vertical-align:middle;border:0;">
<span style="display:inline-block;vertical-align:middle;padding-left:10px;font-family:{FONT};font-size:24px;font-weight:800;letter-spacing:-0.5px;"><span style="color:{LOGO_GREEN};">Future</span><span style="color:{ROYAL_BLUE};">Roots</span></span>
</td></tr>
<tr><td style="background-color:{CARD};border-radius:12px;padding:36px 40px;">
<p style="margin:0 0 16px 0;font-family:{FONT};font-size:18px;font-weight:700;line-height:1.4;color:{HEADING};">{_multiline(greeting)}</p>
{body_paragraphs}{highlight_html}{cta_html}{footnote_html}
</td></tr>
<tr><td style="padding:24px 8px 0 8px;font-family:{FONT};font-size:13px;line-height:1.7;color:{MUTED};">
With warmth,<br>The FutureRoots team
<br><br>
<span style="color:{MUTED};">FutureRoots &middot; {TAGLINE}</span><br>
A private space for your family, sent because this address is part of a FutureRoots family.
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
