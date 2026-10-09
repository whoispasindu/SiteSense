#!/usr/bin/env bash
# One-off GitHub setup for SiteSense: labels, one milestone per build phase, and a protected
# main branch. Needs the GitHub CLI, signed in with admin rights on the repository:
#
#   gh auth login
#   bash scripts/github-bootstrap.sh whoispasindu/SiteSense
#
# Safe to re-run: existing labels and milestones are skipped.
set -euo pipefail

REPO="${1:?usage: github-bootstrap.sh OWNER/REPO}"

echo "== Labels"
while IFS='|' read -r name color description; do
  gh label create "$name" --repo "$REPO" --color "$color" --description "$description" 2>/dev/null \
    && echo "  + $name" || echo "  = $name (exists)"
done <<'LABELS'
feature|ffc21a|New capability
bug|b02e17|Something is broken
security|17160f|Security hardening or finding
ai|2b4fc4|Models, data and evaluation
docs|6f6a5c|Documentation
tests|2a6e45|Test coverage
good first issue|7057ff|Good for newcomers
LABELS

echo "== Milestones (one per phase)"
existing=$(gh api "repos/$REPO/milestones?state=all&per_page=100" --jq '.[].title')
while IFS='|' read -r title description; do
  if grep -Fxq "$title" <<<"$existing"; then
    echo "  = $title (exists)"
  else
    gh api "repos/$REPO/milestones" -f title="$title" -f description="$description" >/dev/null
    echo "  + $title"
  fi
done <<'PHASES'
Phase 0: Setup and foundations|Running skeleton, CI, database
Phase 1: Authentication, roles and users|Secure sign-in, 6 roles, site access
Phase 2: Projects, BOQ and budget|Projects with imported BOQ and budget lines
Phase 3: Schedule basics|Tasks and planned progress curve
Phase 4: Daily site reports|Report form, photos, weather auto-fill
Phase 5: Materials, approvals and rules engine|Full request to delivery workflow
Phase 6: Demo data and risk model v1|First AI feature on the dashboard (v0.1)
Phase 7: Report NLP classifier|AI tags issues in reports
Phase 8: Cost control, claims and variations|Budget forecast, claims, variations
Phase 9: Advanced schedule|Critical path, Gantt, weather and stop-work rules
Phase 10: Risk model v2, what-if and supplier model|Explained forecasts and recovery planner
Phase 11: Dashboard, alerts and AI briefing|Full dashboard and notifications
Phase 12: Client portal|Read-only client view with variation approval
Phase 13: Hardening and deployment|Secure, tested, deployed demo
Phase 14: Testing, UAT and evaluation|Release v1.0
PHASES

echo "== Protect main (pull requests only, CI must pass, no force pushes)"
gh api -X PUT "repos/$REPO/branches/main/protection" --input - >/dev/null <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Backend · lint, types, tests, migrations",
      "Frontend · lint, types, tests, build",
      "Security · dependencies and secrets"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": { "required_approving_review_count": 0 },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
echo "  main is protected"

echo "== Security features"
gh api -X PUT "repos/$REPO/vulnerability-alerts" >/dev/null && echo "  Dependabot alerts on"
gh api -X PUT "repos/$REPO/automated-security-fixes" >/dev/null && echo "  Dependabot security updates on"
gh api -X PATCH "repos/$REPO" --input - >/dev/null <<'JSON' && echo "  secret scanning + push protection on"
{ "security_and_analysis": { "secret_scanning": { "status": "enabled" }, "secret_scanning_push_protection": { "status": "enabled" } } }
JSON
gh api -X PUT "repos/$REPO/private-vulnerability-reporting" >/dev/null && echo "  private vulnerability reporting on"

echo "Done. Create the Projects board in the GitHub UI (Projects -> New project -> Board) and link the repository."
