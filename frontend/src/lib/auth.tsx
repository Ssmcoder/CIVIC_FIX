import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, authApi, setAccessToken, setUnauthorizedHandler, type AdminLoginResponse } from './api'

export type UiRole = 'citizen' | 'official' | 'admin'

export interface CitizenProfile {
  name?: string
  email?: string
  /** tracking tokens the citizen has saved locally (public_id -> secret) */
  tokens: Record<string, string>
}

interface AuthState {
  role: UiRole | null
  admin: AdminLoginResponse['admin'] | null
  citizen: CitizenProfile | null
  ready: boolean
}

interface AuthCtx extends AuthState {
  loginAdmin: (username: string, password: string, totp?: string) => Promise<AdminLoginResponse>
  logoutAdmin: () => Promise<void>
  /** citizen "session" — local profile + saved tracking secrets (backend has no citizen accounts yet) */
  loginCitizen: (p: CitizenProfile) => void
  logoutCitizen: () => void
  saveTrackingToken: (publicId: string, token: string) => void
  removeTrackingToken: (publicId: string) => void
  trackingTokenFor: (publicId: string) => string | undefined
}

const Ctx = createContext<AuthCtx | null>(null)
const LS_CITIZEN = 'cr_citizen'
const LS_ADMIN_META = 'cr_admin_meta'

function roleFor(backendRole: string): UiRole {
  if (['super_admin', 'state_admin', 'district_admin'].includes(backendRole)) return 'admin'
  return 'official' // municipal_admin, ward_admin
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [state, setState] = useState<AuthState>({ role: null, admin: null, citizen: null, ready: false })

  useEffect(() => {
    try {
      const raw = localStorage.getItem(LS_CITIZEN)
      const citizen = raw ? (JSON.parse(raw) as CitizenProfile) : null
      const meta = localStorage.getItem(LS_ADMIN_META)
      const adminMeta = meta ? (JSON.parse(meta) as AdminLoginResponse['admin']) : null
      // access token itself is memory-only; refresh cookie restores session
      setState({ role: adminMeta ? roleFor(adminMeta.role) : citizen ? 'citizen' : null, admin: adminMeta, citizen, ready: true })
    } catch {
      setState({ role: null, admin: null, citizen: null, ready: true })
    }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAccessToken(null)
      localStorage.removeItem(LS_ADMIN_META)
      setState((s) => ({ ...s, role: s.citizen ? 'citizen' : null, admin: null }))
      qc.clear()
    })
  }, [qc])

  const loginAdmin = useCallback(async (username: string, password: string, totp?: string) => {
    const res = await authApi.login(username, password, totp) // sets cookie via withCredentials? ensure below
    setAccessToken(res.access_token)
    localStorage.setItem(LS_ADMIN_META, JSON.stringify(res.admin))
    setState({ role: roleFor(res.admin.role), admin: res.admin, citizen: null, ready: true })
    qc.clear()
    return res
  }, [qc])

  const logoutAdmin = useCallback(async () => {
    try { await authApi.logout() } catch { /* ignore */ }
    setAccessToken(null)
    localStorage.removeItem(LS_ADMIN_META)
    setState((s) => ({ ...s, role: s.citizen ? 'citizen' : null, admin: null, ready: true }))
    qc.clear()
  }, [qc])

  const persistCitizen = useCallback((c: CitizenProfile | null) => {
    if (c) localStorage.setItem(LS_CITIZEN, JSON.stringify(c))
    else localStorage.removeItem(LS_CITIZEN)
  }, [])

  const loginCitizen = useCallback((p: CitizenProfile) => {
    persistCitizen(p)
    setState((s) => ({ ...s, role: 'citizen', citizen: p }))
  }, [persistCitizen])

  const logoutCitizen = useCallback(() => {
    persistCitizen(null)
    setState((s) => ({ ...s, role: s.admin ? roleFor(s.admin.role) : null, citizen: null }))
  }, [persistCitizen])

  const saveTrackingToken = useCallback((publicId: string, token: string) => {
    setState((s) => {
      const citizen: CitizenProfile = { ...(s.citizen || { tokens: {} }), tokens: { ...(s.citizen?.tokens || {}), [publicId]: token } }
      persistCitizen(citizen)
      return { ...s, citizen, role: s.role || 'citizen' }
    })
  }, [persistCitizen])

  const removeTrackingToken = useCallback((publicId: string) => {
    setState((s) => {
      const tokens = { ...(s.citizen?.tokens || {}) }
      delete tokens[publicId]
      const citizen: CitizenProfile = { ...(s.citizen || { tokens: {} }), tokens }
      persistCitizen(citizen)
      return { ...s, citizen }
    })
  }, [persistCitizen])

  const trackingTokenFor = useCallback((publicId: string) => state.citizen?.tokens[publicId], [state.citizen])

  const value = useMemo<AuthCtx>(() => ({
    ...state, loginAdmin, logoutAdmin, loginCitizen, logoutCitizen,
    saveTrackingToken, removeTrackingToken, trackingTokenFor,
  }), [state, loginAdmin, logoutAdmin, loginCitizen, logoutCitizen, saveTrackingToken, removeTrackingToken, trackingTokenFor])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth outside provider')
  return ctx
}

export { api }
