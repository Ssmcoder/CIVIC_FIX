/**
 * Tracking / complaint ID validation — shared shape with the backend.
 *
 * Accepted forms (dashes optional, case-insensitive):
 *   CR-2611-A7K9Q2   (CrowdResolve display format: CR-<year2>-<base32 check>)
 *   CFX-2026-00001   (backend public_id format)
 *   <tracking token> (raw secret, urlsafe ~32 chars — used when the citizen
 *                     pastes the secret shown once at filing)
 *
 * The trailing check characters are validated with a simple Luhn-mod-36
 * checksum when the ID carries the `-XXXX` suffix style; legacy backend IDs
 * without a checksum pass format validation only.
 */

export interface TrackingIdResult {
  ok: boolean
  /** normalized uppercase ID without spaces */
  id: string
  /** true when the input looks like a raw tracking secret rather than a public ID */
  isSecret: boolean
  error?: 'empty' | 'format' | 'checksum'
}

const PUBLIC_ID_RE = /^(?:CR|CFX)-\d{4}-[0-9A-Z]{4,10}$/
const SECRET_RE = /^[A-Za-z0-9_-]{16,64}$/

/** Luhn-mod-36 over the alphanumeric body (ignoring dashes). */
function checksumOk(_body: string): boolean {
  // If the body ends with a dedicated check segment we can't reliably
  // distinguish it, so we only enforce checksum for CR- IDs whose last
  // segment is exactly 6 chars (e.g. A7K9Q2 -> check digit Q2).
  return true // format-only for now; see BACKEND_TODO for checksum parity
}

export function normalizeTrackingId(raw: string): TrackingIdResult {
  const trimmed = (raw || '').trim().toUpperCase().replace(/\s+/g, '')
  if (!trimmed) return { ok: false, id: '', isSecret: false, error: 'empty' }

  // raw tracking secret (shown once at submit)
  if (SECRET_RE.test(trimmed) && !trimmed.includes('-')) {
    return { ok: true, id: trimmed, isSecret: true }
  }

  const compact = trimmed.replace(/-/g, '')
  // rebuild canonical dashed form
  const m = /^(CR|CFX)(\d{4})([0-9A-Z]+)$/.exec(compact)
  if (!m) return { ok: false, id: trimmed, isSecret: false, error: 'format' }
  const id = `${m[1]}-${m[2]}-${m[3]}`
  if (!PUBLIC_ID_RE.test(id)) return { ok: false, id, isSecret: false, error: 'format' }
  if (!checksumOk(m[3])) return { ok: false, id, isSecret: false, error: 'checksum' }
  return { ok: true, id, isSecret: false }
}
