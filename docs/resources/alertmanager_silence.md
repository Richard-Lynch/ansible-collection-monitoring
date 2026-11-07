<!--
Copyright: (c) 2026, Richard Lynch
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Resource model: `alertmanager_silence`

The contract `plugins/module_utils/alertmanager/client.py` implements and a provider in another
language would implement from (richard_lynch.common ADR-C6, ADR-C11). The fixtures that drive the
Python fake server are the same recordings an `httptest` handler would read.

| Aspect | Rule |
| --- | --- |
| API | Alertmanager v2: `GET /api/v2/silences`, `POST /api/v2/silences`, `DELETE /api/v2/silence/{id}` |
| Identity | `comment` (exact) + the normalized matcher set. Never the id: ids are server-generated and change on refresh. |
| Normalized state | `comment`, `created_by`, `ends_at` rounded to the minute (UTC, RFC 3339), `matchers` sorted by `(name, value, isRegex, isEqual)` with both booleans explicit. |
| Server-managed, dropped | `id`, `status`, `updatedAt`, and `startsAt` (an active silence's start is when it was made; "silenced until T" is one state however often it is re-asked). |
| Present | exactly one non-expired silence with the identity, ending at `ends_at`. Several = duplicates: the newest (`updatedAt`) is the resource; the rest are reported and expired on `absent`. |
| Create | `POST` once (not retried: creating is not idempotent). |
| Update | `POST` carrying the current `id`: Alertmanager expires the old record and stores the replacement in one call. |
| Delete | `DELETE /api/v2/silence/{id}` for the resource and each duplicate; a 404 is already-absent. |
| Read-back | after every write the identity is read again; `remaining` drift is a FAILURE with `applied: true`. |
| Check mode | read only; `changed`/`diff` are predictions, `predicted: true`. |
| Secrets | the optional bearer `token` is `no_log`, redacted from errors and diffs by key and value. |
| Errors | Alertmanager's 400 text is surfaced with the hint "a matcher must have name and value; endsAt must be after startsAt and in the future". |
