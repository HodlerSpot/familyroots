# FutureRoots — Agent Team

The repo ships a role-based agent team in `.claude/agents/`. Invoke them via the Agent tool (or let Claude Code auto-select by description). All agents treat `docs/vision.md` as the source of truth.

## The team

| Agent | Role | Writes code? |
|---|---|---|
| `ceo` | Vision guardian — scope calls, prioritization, positioning, business model | No (advisory) |
| `product-manager` | Turns vision into specs (`docs/specs/`) with acceptance criteria | Docs only |
| `architect` | System/data design, keeps `docs/architecture.md` + `docs/data-model.md` current, reviews for serverless/cost/compliance fit | Docs only |
| `ux-designer` | Flows, mockups, accessibility (`docs/design/`) — especially grandparent flows | Docs/mockups |
| `brand-guardian` | Voice, naming, all user-facing copy; enforces the no-crypto-jargon rule (`docs/brand/`) | Copy/docs |
| `backend-engineer` | FastAPI + Postgres implementation in `apps/api` | Yes |
| `frontend-engineer` | Next.js implementation in `apps/web` | Yes |
| `qa-engineer` | Tests access control, money handling, consent, and the north-star flow | Tests |
| `compliance-officer` | COPPA/GDPR/PIPEDA review; BLOCKER/REQUIRED/ADVISORY findings | No (advisory) |

## Standard feature workflow

1. **product-manager** writes the spec (`docs/specs/<feature>.md`)
2. **ux-designer** designs the flow if user-facing (grandparent flows always)
3. **architect** signs off on data/API changes (updates design docs)
4. **compliance-officer** pre-reviews anything touching child data, consent, media, or money
5. **backend-engineer** and **frontend-engineer** implement (can run in parallel once the API contract is agreed)
6. **brand-guardian** reviews all user-facing strings
7. **qa-engineer** verifies acceptance criteria end-to-end
8. Escalate scope/vision disputes to **ceo**

Lightweight changes don't need the full chain — but anything touching children's data or money always gets compliance-officer review, and anything user-facing always gets brand-guardian review.
