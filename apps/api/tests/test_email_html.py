"""The branded HTML email part: written alongside the plain-text outbox file,
carries the logo, and stays free of crypto vocabulary (brand rule)."""

import re

from .conftest import create_family, signup

BANNED = ("wallet", "blockchain", "crypto", "token", "web3")


def _strip_urls(html: str) -> str:
    """URL paths are exempt from the banned-words check (e.g. /invites/{token}
    links and randomly generated tokens inside href/src attributes)."""
    return re.sub(r'(href|src)="[^"]*"', "", html)


def test_invite_email_writes_branded_html_to_outbox(client, tmp_path, monkeypatch):
    from app.services import email as email_module

    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(tmp_path))

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    for f in list(tmp_path.glob("*.txt")) + list(tmp_path.glob("*.html")):
        f.unlink()  # drop the welcome email; this test is about the invite
    r = client.post(
        f"/families/{family_id}/invites",
        json={"email": "gran@example.com", "role": "grandparent"},
        headers=parent,
    )
    assert r.status_code == 201

    # The plain-text part is untouched; the HTML part sits beside it.
    txt_files = list(tmp_path.glob("*.txt"))
    html_files = list(tmp_path.glob("*.html"))
    assert len(txt_files) == 1
    assert len(html_files) == 1
    assert html_files[0].stem == txt_files[0].stem

    html = html_files[0].read_text(encoding="utf-8")
    assert "https://futureroots.app/logo-mark.png" in html
    assert 'alt="FutureRoots"' in html
    assert "/invites/" in html  # the CTA points at the accept page
    # Brand rule: no crypto vocabulary in user-facing text (URLs exempted)
    stripped = _strip_urls(html).lower()
    for banned in BANNED:
        assert banned not in stripped


def test_welcome_email_html_is_branded_and_clean(client, tmp_path, monkeypatch):
    from app.services import email as email_module

    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(tmp_path))
    signup(client, "newfamily@example.com", "Pat Parent")

    html_files = list(tmp_path.glob("*.html"))
    assert len(html_files) == 1
    html = html_files[0].read_text(encoding="utf-8")
    assert "https://futureroots.app/logo-mark.png" in html
    assert "Pat Parent" in html
    stripped = _strip_urls(html).lower()
    for banned in BANNED:
        assert banned not in stripped


def test_render_email_escapes_user_provided_values():
    from app.services.email_templates import render_email

    html = render_email(
        preheader='pre <img src="x">',
        greeting="Hi <b>Pat</b>,",
        paragraphs=['A "note" & <script>alert(1)</script>'],
        highlight="Emma's <big> day",
        cta_label="Click <here>",
        cta_url="https://example.com/?a=1&b=2",
        footnote="fine < print",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>Pat</b>" not in html
    assert "Click <here>" not in html
    assert 'href="https://example.com/?a=1&amp;b=2"' in html
