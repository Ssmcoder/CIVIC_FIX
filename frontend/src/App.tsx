import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider, useAuth, type UiRole } from './lib/auth'
import './i18n'
import { ErrorBoundary } from './components/ErrorBoundary'
import { OfflineBanner } from './components/OfflineBanner'
import { PublicLayout } from './components/layout/PublicLayout'
import { AppShell } from './components/layout/AppShell'
import { Skeleton } from './components/ui/primitives'

const Landing = lazy(() => import('./pages/Landing').then((m) => ({ default: m.Landing })))
const TrackResult = lazy(() => import('./pages/TrackResult').then((m) => ({ default: m.TrackResult })))
const FileComplaint = lazy(() => import('./pages/FileComplaint').then((m) => ({ default: m.FileComplaint })))
const StaticPage = lazy(() => import('./pages/StaticPages').then((m) => ({ default: m.StaticPage })))
const DesignPage = lazy(() => import('./pages/DesignPage').then((m) => ({ default: m.DesignPage })))
const NotFound = lazy(() => import('./pages/NotFound').then((m) => ({ default: m.NotFound })))
const CitizenAuth = lazy(() => import('./pages/auth/AuthPages').then((m) => ({ default: m.CitizenAuth })))
const OfficialAuth = lazy(() => import('./pages/auth/AuthPages').then((m) => ({ default: m.OfficialAuth })))
const AdminLogin = lazy(() => import('./pages/auth/AuthPages').then((m) => ({ default: m.AdminLogin })))
const CitizenDashboard = lazy(() => import('./pages/dashboards').then((m) => ({ default: m.CitizenDashboard })))
const OfficialDashboard = lazy(() => import('./pages/dashboards').then((m) => ({ default: m.OfficialDashboard })))
const AdminDashboard = lazy(() => import('./pages/dashboards').then((m) => ({ default: m.AdminDashboard })))
const ComplaintDetail = lazy(() => import('./pages/dashboards').then((m) => ({ default: m.ComplaintDetail })))
const ComplaintsTable = lazy(() => import('./pages/dashboards').then((m) => ({ default: m.ComplaintsTable })))
const AdminUsers = lazy(() => import('./pages/dashboards').then((m) => ({ default: m.AdminUsers })))
const AdminSla = lazy(() => import('./pages/dashboards').then((m) => ({ default: m.AdminSla })))
const AuditLogs = lazy(() => import('./pages/dashboards').then((m) => ({ default: m.AuditLogs })))
const NotificationsPage = lazy(() => import('./pages/dashboards').then((m) => ({ default: m.NotificationsPage })))

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } },
})

function PageLoader() {
  return <div className="space-y-4 p-6"><Skeleton className="h-10 w-64" /><Skeleton className="h-64 w-full" /></div>
}

function RequireRole({ roles, children }: { roles: UiRole[]; children: React.ReactNode }) {
  const { role, ready } = useAuth()
  const loc = useLocation()
  if (!ready) return <PageLoader />
  if (!role || !roles.includes(role)) return <Navigate to="/" state={{ from: loc }} replace />
  return <>{children}</>
}

function DashboardRouter() {
  const { role } = useAuth()
  if (role === 'official') return <OfficialDashboard />
  if (role === 'admin') return <AdminDashboard />
  return <CitizenDashboard />
}

function ScrollTop() {
  const { pathname } = useLocation()
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])
  return null
}

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <BrowserRouter>
            <ScrollTop />
            <OfflineBanner />
            <Suspense fallback={<PageLoader />}>
              <Routes>
                {/* public */}
                <Route element={<PublicLayout />}>
                  <Route index element={<Landing />} />
                  <Route path="track/:trackingId" element={<TrackResult />} />
                  <Route path="complaint/new" element={<FileComplaint />} />
                  <Route path="login/citizen" element={<CitizenAuth />} />
                  <Route path="login/citizen/signup" element={<CitizenAuth />} />
                  <Route path="login/official" element={<OfficialAuth />} />
                  <Route path="login/official/signup" element={<OfficialAuth />} />
                  <Route path="admin/login" element={<AdminLogin />} />
                  <Route path=":slug" element={<StaticPage />} />
                </Route>

                {/* authed dashboards */}
                <Route element={<AppShell />}>
                  <Route path="dashboard" element={<DashboardRouter />} />
                  <Route path="notifications" element={<RequireRole roles={['citizen']}><NotificationsPage /></RequireRole>} />
                  <Route path="profile" element={<RequireRole roles={['citizen']}><CitizenProfile /></RequireRole>} />
                  <Route path="queue" element={<RequireRole roles={['official']}><ComplaintsTable /></RequireRole>} />
                  <Route path="analytics" element={<RequireRole roles={['official', 'admin']}><OfficialDashboard /></RequireRole>} />
                  <Route path="team" element={<RequireRole roles={['official']}><AdminUsers /></RequireRole>} />
                  <Route path="settings" element={<RequireRole roles={['official', 'admin']}><SettingsPage /></RequireRole>} />
                  <Route path="admin/complaints" element={<RequireRole roles={['admin', 'official']}><ComplaintsTable admin /></RequireRole>} />
                  <Route path="admin/complaints/:id" element={<RequireRole roles={['admin', 'official']}><ComplaintDetail /></RequireRole>} />
                  <Route path="admin/users" element={<RequireRole roles={['admin']}><AdminUsers /></RequireRole>} />
                  <Route path="admin/departments" element={<RequireRole roles={['admin']}><AdminUsers /></RequireRole>} />
                  <Route path="admin/sla" element={<RequireRole roles={['admin']}><AdminSla /></RequireRole>} />
                  <Route path="admin/analytics" element={<RequireRole roles={['admin']}><AdminDashboard /></RequireRole>} />
                  <Route path="admin/audit" element={<RequireRole roles={['admin']}><AuditLogs /></RequireRole>} />
                  <Route path="admin/settings" element={<RequireRole roles={['admin']}><SettingsPage /></RequireRole>} />
                  <Route path="design" element={<DesignPage />} />
                </Route>

                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

import { Card, CardHeader, Button, Input, Field, Avatar } from './components/ui/primitives'
import { useAuth as useAuth2 } from './lib/auth'
import { useTranslation } from 'react-i18next'

function CitizenProfile() {
  const { citizen, loginCitizen } = useAuth2()
  const { t } = useTranslation()
  return (
    <Card className="max-w-lg">
      <CardHeader title={t('nav.profile')} />
      <div className="flex items-center gap-4">
        <Avatar name={citizen?.name} className="h-14 w-14 text-lg" />
        <div>
          <p className="font-semibold">{citizen?.name || 'Citizen'}</p>
          <p className="text-sm text-[var(--text-muted)]">{citizen?.email}</p>
        </div>
      </div>
      <form className="mt-4 space-y-3" onSubmit={(e) => { e.preventDefault(); const fd = new FormData(e.currentTarget); loginCitizen({ name: String(fd.get('name')), email: String(fd.get('email')), tokens: citizen?.tokens || {} }) }}>
        <Field label={t('auth.fullName')}><Input name="name" defaultValue={citizen?.name} /></Field>
        <Field label={t('auth.email')}><Input name="email" type="email" defaultValue={citizen?.email} /></Field>
        <Button type="submit" size="sm">Save</Button>
      </form>
    </Card>
  )
}

function SettingsPage() {
  const { t } = useTranslation()
  return (
    <Card className="max-w-xl">
      <CardHeader title={t('nav.settings')} />
      <p className="text-sm text-[var(--text-muted)]">Notification preferences, contact details and department routing settings will appear here once the backend settings endpoints ship (see FRONTEND.md).</p>
    </Card>
  )
}
