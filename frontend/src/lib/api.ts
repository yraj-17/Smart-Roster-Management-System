// Thin fetch wrapper around the FastAPI backend.
// Errors follow the backend's uniform model: {"error": {"code", "message", "details"}}.

const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''
const ACTOR_KEY = 'roster.actor'

export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  constructor(status: number, code: string, message: string, details: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
  get isConflict() {
    return this.status === 409
  }
}

export function getActor(): string {
  try {
    return localStorage.getItem(ACTOR_KEY) || 'ops.manager'
  } catch {
    return 'ops.manager'
  }
}

export function setActor(name: string) {
  try {
    localStorage.setItem(ACTOR_KEY, name)
  } catch {
    /* storage unavailable: keep default */
  }
}

type Query = Record<string, string | number | boolean | null | undefined>

function url(path: string, query?: Query) {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  const q = qs.toString()
  return `${BASE}/api${path}${q ? `?${q}` : ''}`
}

async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown; text?: string } = {}): Promise<T> {
  const headers: Record<string, string> = { 'X-Actor': getActor() }
  let body: BodyInit | undefined
  if (opts.text !== undefined) {
    headers['Content-Type'] = 'text/csv'
    body = opts.text
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  let res: Response
  try {
    res = await fetch(url(path, opts.query), { method, headers, body })
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the API server. Is the backend running?', null)
  }
  const ct = res.headers.get('content-type') ?? ''
  const payload = ct.includes('application/json') ? await res.json() : await res.text()
  if (!res.ok) {
    const err = typeof payload === 'object' && payload?.error ? payload.error : null
    throw new ApiError(res.status, err?.code ?? `http_${res.status}`, err?.message ?? res.statusText, err?.details ?? null)
  }
  return payload as T
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>('GET', path, { query }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>('POST', path, { body: body ?? {}, query }),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, { body }),
  del: <T>(path: string) => request<T>('DELETE', path),
  postText: <T>(path: string, text: string) => request<T>('POST', path, { text }),
  downloadUrl: (path: string) => url(path),
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'validation_error' && Array.isArray(e.details)) {
      return e.details.map((d: { field: string; message: string }) => `${d.field || 'request'}: ${d.message}`).join('; ')
    }
    return e.message
  }
  return e instanceof Error ? e.message : String(e)
}
