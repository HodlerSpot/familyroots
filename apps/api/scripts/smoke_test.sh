#!/usr/bin/env bash
# Smoke test against a deployed FutureRoots API.
# Usage: bash smoke_test.sh https://xxxx.execute-api.us-east-1.amazonaws.com
set -euo pipefail
API="${1:?usage: smoke_test.sh <api-url>}"
STAMP=$(date +%s)
PARENT_EMAIL="smoke-parent-$STAMP@example.com"
GRAN_EMAIL="smoke-gran-$STAMP@example.com"

tok() { sed 's/.*"access_token":"\([^"]*\)".*/\1/'; }
id() { sed 's/.*"id":"\([^"]*\)".*/\1/'; }
fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

echo "1. health"
curl -sf "$API/health" >/dev/null || fail "health"

echo "2. parent signup + family + child"
PARENT=$(curl -sf -X POST "$API/auth/signup" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$PARENT_EMAIL\",\"display_name\":\"Smoke Parent\",\"password\":\"Password123!\"}" | tok)
FAMILY_ID=$(curl -sf -X POST "$API/families" -H "Authorization: Bearer $PARENT" \
  -H 'Content-Type: application/json' -d '{"name":"Smoke Family"}' | id)
CHILD_ID=$(curl -sf -X POST "$API/families/$FAMILY_ID/children" -H "Authorization: Bearer $PARENT" \
  -H 'Content-Type: application/json' \
  -d '{"first_name":"Smokey","birthdate":"2018-05-01","parental_consent":true}' | id)

echo "3. invite grandparent (email goes to SES; may be sandbox-suppressed)"
curl -sf -X POST "$API/families/$FAMILY_ID/invites" -H "Authorization: Bearer $PARENT" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$GRAN_EMAIL\",\"role\":\"grandparent\"}" >/dev/null || echo "   (invite email failed — expected in SES sandbox with unverified recipient)"

echo "4. milestone + feed"
curl -sf -X POST "$API/children/$CHILD_ID/milestones" -H "Authorization: Bearer $PARENT" \
  -H 'Content-Type: application/json' -d '{"title":"Smoke milestone"}' >/dev/null \
  || echo "   (milestone email may fail in sandbox; checking feed anyway)"
curl -sf "$API/families/$FAMILY_ID/feed" -H "Authorization: Bearer $PARENT" | grep -q milestone || fail "feed"

echo "5. contribution -> ledger"
CONTRIB_ID=$(curl -sf -X POST "$API/children/$CHILD_ID/contributions" -H "Authorization: Bearer $PARENT" \
  -H 'Content-Type: application/json' -d '{"amount_cents":1000}' | id)
curl -sf -X POST "$API/contributions/$CONTRIB_ID/confirm" -H "Authorization: Bearer $PARENT" >/dev/null 2>&1 \
  || echo "   (confirm email to parents skipped: actor is the only parent)"
BALANCE=$(curl -sf "$API/children/$CHILD_ID/fund" -H "Authorization: Bearer $PARENT" | sed 's/.*"balance_cents":\([0-9]*\).*/\1/')
[ "$BALANCE" = "975" ] || fail "balance expected 975 got $BALANCE"

echo "6. media presigned upload"
TICKET=$(curl -sf -X POST "$API/children/$CHILD_ID/media" -H "Authorization: Bearer $PARENT" \
  -H 'Content-Type: application/json' -d '{"content_type":"image/png"}')
MEDIA_ID=$(echo "$TICKET" | sed 's/.*"media_id":"\([^"]*\)".*/\1/')
UPLOAD_URL=$(echo "$TICKET" | sed 's/.*"upload_url":"\([^"]*\)".*/\1/' | sed 's/\\u0026/\&/g')
printf 'fakepng' | curl -sf -X PUT "$UPLOAD_URL" -H 'Content-Type: image/png' --data-binary @- >/dev/null || fail "presigned PUT"
curl -sf -X POST "$API/media/$MEDIA_ID/complete" -H "Authorization: Bearer $PARENT" >/dev/null || fail "media complete"

echo "SMOKE PASS"
