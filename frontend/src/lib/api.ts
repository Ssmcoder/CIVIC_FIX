import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'

/**
 * Typed API client for the CivicFix backend.
 * Base URL: VITE_API_URL (default '/api' → dev proxy → :8000).
 * Admin JWT is kept in memory; refresh uses the HttpOnly cookie.
 */

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) || '/api'

export const api = axios.create({
  baseURL: API_URL,
  timeout: 20000,
  withCredentials: true, // refresh-token cookie (SameSite=Strict)
  headers: { 'Content-Type': 'application/json' },
})

let accessToken: string | null = null
let onUnauthorized: (() => void) | null = null

export function setAccessToken(t: string | null) {
  accessToken = t
}
export function getAccessToken() {
  return accessToken
}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

api.interceptors.request.use((cfg: InternalAxiosRequestConfig) => {
  if (accessToken && cfg.headers) {
    cfg.headers.Authorization = `Bearer ${accessToken}`
  }
  return cfg
})

let refreshing: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
  try {
    const r = await axios.post(`${API_URL}/auth/refresh`, {}, { withCredentials: true })
    const t = r.data?.access_token
    if (t) {
      accessToken = t
      return true
    }
  } catch {
    /* fallthrough */
  }
  return false
}

api.interceptors.response.use(
  (r) => r,
  async (err: AxiosError) => {
    const orig = err.config as InternalAxiosRequestConfig & { _retried?: boolean }
    const url = orig?.url || ''
    const isAuthCall = url.includes('/auth/login') || url.includes('/auth/refresh')
    if (err.response?.status === 401 && !orig?._retried && !isAuthCall) {
      orig._retried = true
      refreshing = refreshing || tryRefresh()
      const ok = await refreshing
      refreshing = null
      if (ok) {
        if (orig.headers) orig.headers.Authorization = `Bearer ${accessToken}`
        return api(orig)
      }
      onUnauthorized?.()
    }
    return Promise.reject(err)
  },
)

/** Consistent error surface for UI toasts. */
export function apiErrorMessage(e: unknown, fallback = 'Something went wrong'): string {
  const ax = e as AxiosError<{ error?: { message?: string; code?: string } }>
  if (ax?.response?.status === 429) return 'Too many requests — please slow down and retry.'
  const msg = ax?.response?.data?.error?.message
  if (typeof msg === 'string' && msg) return msg
  if (ax?.response?.data && typeof ax.response.data === 'object') {
    const d = ax.response.data as { detail?: unknown }
    if (typeof d.detail === 'string') return d.detail
  }
  if (!ax?.response) return 'Network error — check your connection.'
  return fallback
}

// ---------------------------------------------------------------- typed calls

export interface ComplaintSubmit {
  description: string
  lat?: number | null
  lon?: number | null
  landmark_text?: string | null
  manual_location_confirmed?: boolean
  language?: string
  source?: string
  transcript?: string | null
  contact_phone?: string | null
  contact_email?: string | null
  anonymous?: boolean
  category_override?: string | null
}

export interface ComplaintCreated {
  public_id: string
  tracking_token: string
  status: string
  category: string
  category_label: string
  issue_type?: string
  ai_confidence?: number
  ai_explanation?: string
  priority_band: string
  priority_score: number
  priority_factors?: Record<string, unknown>
  sla_deadline?: string | null
  department?: string | null
  incident_id?: string | null
  location?: {
    lat?: number | null
    lon?: number | null
    landmark?: string | null
    confidence?: number | null
    verified?: boolean
    candidates?: { name: string; lat: number; lon: number }[]
    method?: string
  }
  possible_duplicates?: unknown[]
  review_reasons?: string[]
  message?: string
}

export interface TrackedComplaint {
  id: string
  public_id: string
  status: string
  category: string
  category_label: string
  issue_type?: string
  description?: string
  language?: string
  source?: string
  severity?: string
  severity_score?: number
  priority_score?: number
  priority_band: string
  sla_deadline?: string | null
  sla_breached?: boolean
  department_id?: string | null
  location?: { lat?: number; lon?: number; landmark?: string; confidence?: number; verified?: boolean }
  created_at?: string
  updated_at?: string
  resolved_at?: string | null
  review_reason?: string | null
  incident_id?: string | null
  incident?: { id: string; title: string; status: string; citizens_affected: number; priority_band: string } | null
  status_history?: { from: string; to: string; actor: string; note?: string; at?: string }[]
  evidence?: { id: string; kind: string; name?: string; mime?: string; size?: number; caption?: string; is_resolution?: boolean; created_at?: string }[]
  department?: string | null
  citizens_affected?: number
  can_verify?: boolean
  resolution_evidence?: { id: string; kind: string; name?: string; caption?: string; created_at?: string }[]
}

export const complaintsApi = {
  submit: (body: ComplaintSubmit) =>
    api.post<ComplaintCreated>('/complaints', body).then((r) => r.data),
  track: (token: string) =>
    api.get<TrackedComplaint>(`/complaints/track/${encodeURIComponent(token)}`).then((r) => r.data),
  verify: (publicId: string, token: string, action: 'confirm' | 'reject', reason?: string) =>
    api.post(`/complaints/${encodeURIComponent(publicId)}/verify`, { token, action, reason }).then((r) => r.data),
  nearby: (lat: number, lon: number, radiusM = 500) =>
    api.get('/incidents/nearby', { params: { lat, lon, radius_m: radiusM } }).then((r) => r.data),
  support: (incidentId: string, token: string) =>
    api.post(`/incidents/${incidentId}/support`, { token }).then((r) => r.data),
}

export interface AdminLoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  admin: {
    id: string; email: string; username: string; full_name?: string
    role: string; jurisdiction_id?: string | null; mfa_enabled: boolean
    must_change_password?: boolean
  }
}

export const authApi = {
  login: (username: string, password: string, totp?: string) =>
    api.post<AdminLoginResponse>('/auth/login', { username, password, totp_code: totp }).then((r) => r.data),
  logout: () => api.post('/auth/logout').then((r) => r.data),
  me: () => api.get('/admin/me').then((r) => r.data),
}

export const adminApi = {
  dashboard: () => api.get('/admin/dashboard').then((r) => r.data),
  complaints: (params?: Record<string, unknown>) =>
    api.get('/admin/complaints', { params }).then((r) => r.data),
  complaint: (id: string) => api.get(`/admin/complaints/${id}`).then((r) => r.data),
  patchComplaint: (id: string, body: Record<string, unknown>) =>
    api.patch(`/admin/complaints/${id}`, body).then((r) => r.data),
  assign: (id: string, body: Record<string, unknown>) =>
    api.post(`/admin/complaints/${id}/assign`, body).then((r) => r.data),
  resolve: (id: string, body: Record<string, unknown>) =>
    api.post(`/admin/complaints/${id}/resolve`, body).then((r) => r.data),
  incidents: () => api.get('/admin/incidents').then((r) => r.data),
  departments: () => api.get('/admin/departments').then((r) => r.data),
  jurisdictions: () => api.get('/admin/jurisdictions').then((r) => r.data),
  slaRules: () => api.get('/admin/sla-rules').then((r) => r.data),
  priorityConfig: () => api.get('/admin/priority-config').then((r) => r.data),
  notifications: () => api.get('/admin/notifications').then((r) => r.data),
  mlMetrics: () => api.get('/admin/ml/metrics').then((r) => r.data),
}

export const chatApi = {
  createSession: () => api.post('/chat/sessions', {}).then((r) => r.data),
  send: (sid: string, token: string, content: string) =>
    api.post(`/chat/sessions/${sid}/messages`, { content }, { headers: { 'X-Chat-Token': token } }).then((r) => r.data),
  history: (sid: string, token: string) =>
    api.get(`/chat/sessions/${sid}`, { headers: { 'X-Chat-Token': token } }).then((r) => r.data),
}
