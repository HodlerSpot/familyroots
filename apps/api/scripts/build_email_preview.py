from pathlib import Path

from app.services.email_templates import render_email

# Run from apps/api:  uv run python scripts/build_email_preview.py
out = Path(__file__).resolve().parents[1] / "var" / "email-preview"
out.mkdir(parents=True, exist_ok=True)

(out / "preview_welcome.html").write_text(
    render_email(
        preheader="Your family's private space for memories, milestones, and the future.",
        greeting="Hi Pat,",
        paragraphs=[
            "Welcome to FutureRoots, your family's private space for memories, milestones, and building a future together.",
            "🏡 Create your family space and add your children. Each child gets a vault of memories that stays with them for life.",
            "💌 Invite grandparents and relatives with a simple email link.",
            "We're glad your family is here.",
        ],
        cta_label="Create your family space",
        cta_url="https://futureroots.app/family",
    ),
    encoding="utf-8",
)

(out / "preview_milestone.html").write_text(
    render_email(
        preheader="Emma just reached a milestone. Come celebrate!",
        greeting="Hi Grandma Rose,",
        paragraphs=["Wonderful news from your family: Emma just reached a milestone."],
        highlight="First piano recital. She played beautifully!",
        cta_label="Celebrate with a gift to Emma's future",
        cta_url="https://futureroots.app/family/x/child/y/contribute",
        secondary_label="See it on the family feed",
        secondary_url="https://futureroots.app/family/x",
    ),
    encoding="utf-8",
)
print("previews written")
