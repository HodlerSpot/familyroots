"""Main-site issue reporting. Any signed-in family member can report a problem;
reports land in the same BugReport table the admin console reviews (reporter is
a User here, versus a Tester on the testnet harness). No points on the main
site — this is purely a support channel."""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func

from ..deps import CurrentUser, DbSession
from ..models import BugReport

router = APIRouter(tags=["issues"])

MAX_OPEN_REPORTS = 20


class IssueSubmit(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("title", "body")
    @classmethod
    def _trim(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Please add a little more detail")
        return value


class IssueOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str


@router.post("/issues", response_model=IssueOut, status_code=status.HTTP_201_CREATED)
def report_issue(payload: IssueSubmit, db: DbSession, user: CurrentUser) -> IssueOut:
    open_count = (
        db.query(func.count(BugReport.id))
        .filter(BugReport.reporter_user_id == user.id, BugReport.status == "pending")
        .scalar()
    )
    if open_count >= MAX_OPEN_REPORTS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You have several reports awaiting review already. Thank you for the help",
        )
    report = BugReport(reporter_user_id=user.id, title=payload.title, body=payload.body)
    db.add(report)
    db.commit()
    db.refresh(report)
    return IssueOut(id=report.id, title=report.title, status=report.status)
