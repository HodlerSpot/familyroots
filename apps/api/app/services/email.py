"""Email sending abstraction.

Domain code never talks to a provider SDK directly. Local dev writes emails to
a folder (apps/api/var/outbox) so invite links are easy to grab; production
swaps in an SES implementation without touching callers.
"""

from pathlib import Path
from typing import Protocol


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class OutboxEmailSender:
    """Dev sender: prints the email and writes it to var/outbox/."""

    def __init__(self, outbox_dir: Path | None = None) -> None:
        self.outbox_dir = outbox_dir or Path(__file__).resolve().parents[2] / "var" / "outbox"

    def send(self, to: str, subject: str, body: str) -> None:
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        existing = len(list(self.outbox_dir.glob("*.txt")))
        path = self.outbox_dir / f"{existing + 1:04d}.txt"
        path.write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
        # ascii() because the Windows console (cp1252) chokes on emoji in subjects
        print(f"[email] to={to} subject={ascii(subject)} -> {path}")


_sender: EmailSender = OutboxEmailSender()


def get_email_sender() -> EmailSender:
    return _sender
