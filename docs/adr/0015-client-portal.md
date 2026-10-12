# ADR 0015: The client portal, and client access per project

- Status: accepted
- Date: 2026-10-13
- Changes: client access in [ADR 0003](0003-security-baseline.md) and Phase 8 (clients were scoped by site)

## Context

Phase 12 asks for a portal where "clients see honest progress without seeing the contractor's internal
costs". It covers:

- client-only endpoints with separate response schemas;
- progress, the revised handover date and its reason, milestones, approved photos, variations and payments;
- TC-07 and a schema test showing that no cost field appears in any client response.

The project owner decided:

- **Handover date.** The PM publishes a date and a reason, with the programme forecast and the risk
  range shown as suggestions.
  - The client sees it beside the contract date, with the history of earlier dates.
  - The client is notified, and every change is audited.
  - Until a date is published, the client sees the contract date.
  - The PM's dashboard flags a published date as outdated when the programme forecast is more than
    7 working days later than it, or when it has not been reviewed for 30 days. The PM then
    republishes, or confirms it unchanged (also audited).
- **Photos.** Photos are private by default. The PM shares or unshares them one at a time or in bulk,
  and every change is audited. Copies shown to clients carry no metadata.
- **Milestones.** The PM flags programme tasks as client milestones and can give each a
  client-friendly name. Suggested milestones (foundations, structure, roof, finishes, handover) are
  offered when none are flagged.
- **Payments.** Clients see approved and paid claims with the full breakdown, the contract value
  with approved variations, and the retention held so far, with a note that it is released at the end
  of the defects period.
- **Client access is per project.** The Company Admin links each client account to projects.
  - This rule covers every place a client gets data: portal pages, the variation decision,
    notifications and their emails, photos and downloads.
  - Another client's project answers exactly like a project that does not exist.
  - This was decided when the review found the demo had two clients' projects on one site, which site
    scoping would have shown to each other.

## Decision

- **Separate client schemas** (`app/schemas/portal.py`), never subclasses of internal ones. Services
  build them field by field, so an internal field cannot reach a client by inheritance.
  - `test_client_portal.py` walks every client response, fully populated, for cost and internal field
    names at any depth.
  - It also checks that each schema declares none, and that no client schema extends an internal one.
- **What the client sees and does not see.**
  - The client sees the contract they signed: the contract value with approved variations, and approved
    or paid claims (submitted or returned ones stay internal).
  - Certified percentages are rounded to 2 places; the stored value keeps 6.
  - They never see budgets, committed costs, forecasts at current rates, BOQ rates, risk scores,
    internal comments, notes, or who shared or uploaded what.
- **Client access** (`app/services/client_access.py`, table `project_clients`, migration 0015). A
  client reaches a project only through this link, never through a site. Cancelled projects are hidden.
  - `project_for` returns the same 404 ("Project not found.") for a missing project and for one the
    client is not linked to.
  - Variations and photos follow the same rule, each with its own "not found".
  - Only linked clients are notified (`clients_of`); emails are built from those notifications
    (Phase 11), so they follow.
  - Links are set on the client's account (`POST /admin/users/{id}/projects`, audited). They are
    cleared if the account's role changes.
  - Existing client accounts must be linked after upgrading: there is no automatic backfill from
    sites, because that would recreate the leak.
- **The handover date** (`handover_publications`, append-only): "published" rows are what clients see;
  "confirmed" rows record a review and are shown only to the contractor.
  - Each row keeps the programme forecast at the time, as a record.
  - A milestone's expected date is the programme's forecast, never later than the published handover
    date, so the two never contradict each other.
- **Photos.** `report_photos.shared_with_client` (with who and when) is set only by the PM, and only for
  the project's own photos. The bulk call is all-or-nothing.
  - The client endpoint re-checks every file on the way out and re-encodes any that carries EXIF, XMP,
    ICC or a comment (`photos.without_metadata`).
  - This review found that uploads kept JPEG comments, because Pillow writes `info["comment"]` back on
    save. The upload re-encode now clears the info dictionary as well.
- **The UI.**
  - Clients get a simpler top navigation (Your projects, Variations) instead of the staff sidebar.
  - With one project, the client's home opens that project straight away.
  - Staff get a "Client view" tab on each project: the handover date with suggestions, reminders and
    history; milestones with suggestions mapped to tasks by keyword; and photo sharing with bulk select.
  - The PM's dashboard lists dates to review.

## Consequences

- One client account can follow several projects, and several accounts (an owner and their
  consultant) can follow one project.
- The Company Admin must link clients. It is one step, in the user's dialog.
- Site assignment still exists for clients but no longer grants project access. It only decides which
  sites appear in their profile.
- The defects-period end is not stored, so the note on retention states the rule without a date. A
  per-project defects period could add it later.
