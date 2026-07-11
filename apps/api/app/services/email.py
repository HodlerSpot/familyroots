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


class SesEmailSender:
    """Production sender via the SES v2 API (reached through a VPC endpoint)."""

    def __init__(self, from_address: str) -> None:
        import boto3

        self.from_address = from_address
        self.client = boto3.client("sesv2")

    def send(self, to: str, subject: str, body: str) -> None:
        self.client.send_email(
            FromEmailAddress=self.from_address,
            Destination={"ToAddresses": [to]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                }
            },
        )


def _build_sender() -> EmailSender:
    from ..config import settings

    if settings.email_backend == "ses":
        return SesEmailSender(settings.ses_from_address)
    return OutboxEmailSender()


_sender: EmailSender = _build_sender()


def get_email_sender() -> EmailSender:
    return _sender
