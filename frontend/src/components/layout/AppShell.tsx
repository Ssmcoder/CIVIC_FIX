import { useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  LayoutDashboard, FilePlus2, Bell, User, ListChecks, BarChart3, Users, Settings,
  ClipboardList, Building2, Tags, ScrollText, LifeBuoy, Search, Moon, Sun,
  ChevronDown, LogOut, Menu, X,
} from 'lucide-react'
import { useAuth, type UiRole } from '../../lib/auth'
import { Avatar, Kbd } from '../ui/primitives'
import { Footer } from './Footer'
import { TrackIdSearch } from './TrackIdSearch'
import { cn } from '../../lib/utils'
import { ChatWidget } from './ChatWidget'

interface NavItem { to: string; label: string; icon: React.ElementType; end?: boolean }
interface NavGroup { title?: string; items: NavItem[] }

function navFor(role: UiRole, t: (k: string) => string): NavGroup[] {
  const I = (to: string, label: string, icon: React.ElementType, end = false): NavItem => ({ to, label, icon, end })
  if (role === 'citizen') return [{ items: [
    I('/dashboard', t('nav.dashboard'), LayoutDashboard, true),
    I('/complaint/new', t('nav.fileComplaint'), FilePlus2),
    I('/notifications', t('nav.notifications'), Bell),
    I('/profile', t('nav.profile'), User),
  ] }]
  if (role === 'official') return [{ items: [
    I('/dashboard', t('nav.dashboard'), LayoutDashboard, true),
    I('/queue', t('nav.queue'), ClipboardList),
    I('/analytics', t('nav.analytics'), BarChart3),
    I('/team', t('nav.team'), Users),
    I('/settings', t('nav.settings'), Settings),
  ] }]
  return [{ items: [
    I('/dashboard', t('nav.dashboard'), LayoutDashboard, true),
    I('/admin/complaints', t('nav.allComplaints'), ListChecks),
    I('/admin/users', t('nav.officialsUsers'), Users),
    I('/admin/departments', t('nav.departments'), Building2),
    I('/admin/sla', t('nav.categoriesSla'), Tags),
    I('/admin/analytics', t('nav.analytics'), BarChart3),
    I('/admin/audit', t('nav.auditLogs'), ScrollText),
    I('/admin/settings', t('nav.settings'), Settings),
  ] }]
}

function RoleBadge({ role }: { role: UiRole }) {
  const { t } = useTranslation()
  const tones: Record<UiRole, string> = {
    citizen: 'bg-brand-100 text-brand-700 dark:bg-brand-900/40 dark:text-brand-300',
    official: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
    admin: 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
  }
  return <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide', tones[role])}>{t(`topbar.role.${role}`)}</span>
}

export function AppShell() {
  const { t, i18n } = useTranslation()
  const { role, admin, citizen, logoutAdmin, logoutCitizen } = useAuth()
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  const [mobileNav, setMobileNav] = useState(false)
  const [userMenu, setUserMenu] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()

  const groups = useMemo(() => (role ? navFor(role, t) : []), [role, t])
  const pageTitle = useMemo(() => {
    const all = groups.flatMap((g) => g.items)
    const hit = all.find((i) => (i.end ? location.pathname === i.to : location.pathname.startsWith(i.to)))
    return hit?.label || t('app.name')
  }, [groups, location.pathname, t])

  useEffect(() => { setMobileNav(false); setUserMenu(false) }, [location.pathname])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPaletteOpen(true) }
      if (e.key === 'Escape') setPaletteOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const toggleDark = () => {
    const next = !dark
    setDark(next)
    document.documentElement.classList.toggle('dark', next)
    localStorage.setItem('cr_theme', next ? 'dark' : 'light')
  }

  useEffect(() => {
    if (localStorage.getItem('cr_theme') === 'dark' || (!localStorage.getItem('cr_theme') && matchMedia('(prefers-color-scheme: dark)').matches)) {
      document.documentElement.classList.add('dark')
      setDark(true)
    }
  }, [])

  const langs = [{ code: 'en', label: 'EN' }, { code: 'hi', label: 'हिं' }]
  const displayName = admin?.full_name || admin?.username || citizen?.name || citizen?.email || 'Citizen'

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center gap-2 px-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-teal-brand-600 font-display text-lg font-bold text-white">C</div>
        <span className="font-display text-lg font-bold text-[var(--text)]">CrowdResolve</span>
      </div>

      <button onClick={() => setPaletteOpen(true)}
        className="mx-4 mt-2 flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text-faint)] hover:border-brand-300 transition-colors">
        <Search className="h-4 w-4" />
        <span className="flex-1 text-left">{t('nav.commandPalette')}</span>
        <Kbd>⌘K</Kbd>
      </button>

      <nav className="mt-4 flex-1 space-y-4 overflow-y-auto px-3 pb-4" aria-label="Main">
        {groups.map((g, gi) => (
          <div key={gi}>
            {g.title && <p className="mb-1 px-3 text-[11px] font-bold uppercase tracking-wider text-[var(--text-faint)]">{g.title}</p>}
            <ul className="space-y-1">
              {g.items.map((item) => (
                <li key={item.to}>
                  <NavLink to={item.to} end={item.end}
                    className={({ isActive }) => cn(
                      'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300'
                        : 'text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]',
                    )}>
                    <item.icon className="h-4.5 w-4.5" />
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="m-3 rounded-2xl border border-brand-200 bg-gradient-to-br from-brand-50 to-teal-brand-50 p-4 dark:border-brand-800 dark:from-brand-900/20 dark:to-teal-brand-900/20">
        <div className="flex items-center gap-2 text-sm font-semibold text-brand-800 dark:text-brand-200">
          <LifeBuoy className="h-4 w-4" /> {t('nav.needSupport')}
        </div>
        <p className="mt-1 text-xs text-brand-700/80 dark:text-brand-300/80">{t('nav.needSupportBody')}</p>
        <p className="mt-2 text-xs font-bold text-brand-700 dark:text-brand-300">{t('nav.helpline')}: 1800-XXX-XXXX</p>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen">
      {/* desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-[var(--border)] bg-[var(--surface)] lg:block">
        {sidebar}
      </aside>

      {/* mobile drawer */}
      {mobileNav && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileNav(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-[var(--surface)] shadow-2xl">{sidebar}</aside>
        </div>
      )}

      <div className="lg:pl-64">
        {/* top bar */}
        <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--surface)]/80 backdrop-blur">
          <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
            <button className="lg:hidden rounded-lg p-2 hover:bg-[var(--surface-2)]" onClick={() => setMobileNav(true)} aria-label="Open menu">
              {mobileNav ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
            <h1 className="hidden font-display text-lg font-bold text-[var(--text)] sm:block">{pageTitle}</h1>

            <div className="flex-1 max-w-md mx-auto lg:mx-0 lg:ml-6">
              <TrackIdSearch compact />
            </div>

            <div className="ml-auto flex items-center gap-1.5">
              <div className="hidden md:flex rounded-lg border border-[var(--border)] p-0.5" role="group" aria-label={t('topbar.language')}>
                {langs.map((l) => (
                  <button key={l.code} onClick={() => void i18n.changeLanguage(l.code)}
                    className={cn('rounded-md px-2 py-1 text-[11px] font-bold',
                      i18n.language?.startsWith(l.code) ? 'bg-brand-600 text-white' : 'text-[var(--text-muted)]')}
                    aria-pressed={i18n.language?.startsWith(l.code)}>{l.label}</button>
                ))}
              </div>
              <button onClick={toggleDark} className="rounded-lg p-2 text-[var(--text-muted)] hover:bg-[var(--surface-2)]" aria-label={t('topbar.theme')}>
                {dark ? <Sun className="h-4.5 w-4.5" /> : <Moon className="h-4.5 w-4.5" />}
              </button>
              <button className="relative rounded-lg p-2 text-[var(--text-muted)] hover:bg-[var(--surface-2)]" aria-label={t('topbar.notifications')}>
                <Bell className="h-4.5 w-4.5" />
                <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-red-500" />
              </button>
              <div className="relative">
                <button onClick={() => setUserMenu((v) => !v)} className="flex items-center gap-2 rounded-xl p-1.5 hover:bg-[var(--surface-2)]" aria-haspopup="menu" aria-expanded={userMenu}>
                  <Avatar name={displayName} />
                  <div className="hidden text-left sm:block">
                    <p className="text-sm font-semibold leading-tight text-[var(--text)]">{displayName}</p>
                    <RoleBadge role={role || 'citizen'} />
                  </div>
                  <ChevronDown className="hidden h-4 w-4 text-[var(--text-faint)] sm:block" />
                </button>
                {userMenu && (
                  <div className="absolute right-0 mt-2 w-52 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-1.5 shadow-[var(--shadow-pop)]" role="menu">
                    <button onClick={() => { void logoutAdmin(); logoutCitizen(); navigate('/') }}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20">
                      <LogOut className="h-4 w-4" /> {t('topbar.signOut')}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </header>

        {/* page content */}
        <main className="px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
        <Footer />
      </div>

      <ChatWidget />
      {paletteOpen && <CommandPalette onClose={() => setPaletteOpen(false)} navigate={navigate} groups={groups} />}
    </div>
  )
}

function CommandPalette({ onClose, navigate, groups }: { onClose: () => void; navigate: (to: string) => void; groups: NavGroup[] }) {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const items = groups.flatMap((g) => g.items)
  const filtered = items.filter((i) => i.label.toLowerCase().includes(q.toLowerCase()))
  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-black/40 pt-[15vh]" onClick={onClose} role="dialog" aria-modal="true" aria-label={t('nav.commandPalette')}>
      <div className="w-[90%] max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-pop)]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-[var(--border)] px-4">
          <Search className="h-4 w-4 text-[var(--text-faint)]" />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('nav.commandPalette')}
            className="h-12 flex-1 bg-transparent text-sm outline-none" />
          <Kbd>ESC</Kbd>
        </div>
        <ul className="max-h-72 overflow-y-auto p-2">
          {filtered.map((i) => (
            <li key={i.to}>
              <button onClick={() => { navigate(i.to); onClose() }}
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-[var(--text)] hover:bg-[var(--surface-2)]">
                <i.icon className="h-4 w-4 text-brand-600" /> {i.label}
              </button>
            </li>
          ))}
          {filtered.length === 0 && <li className="px-3 py-6 text-center text-sm text-[var(--text-muted)]">{t('table.empty')}</li>}
        </ul>
      </div>
    </div>
  )
}
