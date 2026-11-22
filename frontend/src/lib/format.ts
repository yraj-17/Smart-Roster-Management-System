export const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
export const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** Parse an ISO date (YYYY-MM-DD) as a local calendar date. */
export function parseDate(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}

/** Monday = 0 ... Sunday = 6 (matches the backend). */
export function dow(iso: string): number {
  return (parseDate(iso).getDay() + 6) % 7
}

export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { day: '2-digit', month: 'short' }) {
  if (!iso) return '—'
  return parseDate(iso).toLocaleDateString('en-GB', opts)
}

export function fmtDateTime(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function fmtPct(v: number | null | undefined, digits = 1) {
  return v === null || v === undefined ? '—' : `${Number(v).toFixed(digits)}%`
}

export function monthLabel(year: number, month: number) {
  return `${MONTHS[month - 1]} ${year}`
}

export function iso(y: number, m: number, d: number) {
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

export function lastDay(year: number, month: number) {
  return new Date(year, month, 0).getDate()
}

export function maskToDays(mask: number): number[] {
  return [0, 1, 2, 3, 4, 5, 6].filter((d) => (mask >> d) & 1)
}

export function daysToMask(days: number[]): number {
  return days.reduce((m, d) => m | (1 << d), 0)
}

export function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join('')
}

export function humanize(s: string) {
  return s.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase())
}
