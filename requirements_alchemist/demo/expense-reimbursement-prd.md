# Expense reimbursement portal — demo PRD

## Objective

Replace emailed expense spreadsheets with a traceable workflow that lets employees submit
business expenses, managers review them, and finance export approved claims.

## Roles

- Employee: creates and submits only their own claims.
- Manager: reviews claims submitted by direct reports.
- Finance analyst: views approved claims, records payment, and exports audit data.

## Submission

An employee creates a draft claim containing expense date, category, amount, currency,
business purpose, cost center, and one or more receipt files. Supported receipts are PDF,
PNG, and JPEG, up to 10 MB each. Amount must be greater than zero and the expense date cannot
be in the future. The employee can save an incomplete draft, but submission requires every
field and at least one receipt.

Submitting freezes the employee-editable version and sends the claim to the employee's current
manager. The employee sees the status and submission time. Retrying a timed-out submission must
not create a duplicate claim.

## Manager review

A manager can approve or reject a pending claim for a direct report. A rejection requires a
comment and returns the claim to the employee for correction. A manager cannot review their
own claim. If reporting lines change after submission, the claim remains assigned to the
manager captured at submission until finance explicitly reassigns it.

Concurrent review attempts must not overwrite a completed decision. The second reviewer sees
that the claim has already changed.

## Finance and audit

Finance can export approved, unpaid claims as CSV. The export includes claim ID, employee ID,
cost center, expense date, category, original amount/currency, approved amount, approver, and
approval time. Receipt content is not included. Spreadsheet-leading characters in textual
fields must be neutralized.

Every submission, approval, rejection, reassignment, export, and payment-state change records
actor, action, claim ID, timestamp, and previous/new state. Audit records are retained for
seven years and cannot be edited through the application.

## Quality requirements

- Pages and validation errors must meet WCAG 2.2 AA keyboard and screen-reader expectations.
- Ninety-five percent of ordinary page requests must complete within two seconds under the
  agreed production load profile.
- Receipt files are encrypted in transit and at rest.
- Users can access only claims permitted by their current role and organization.
- Logs and model prompts must not contain receipt content, credentials, or payment account data.

## Open decisions

- Who can reassign a claim when a manager leaves?
- Which currencies and conversion-rate source are supported?
- What is the approved-claim payment integration?
