import { useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ChevronDown, Globe, Menu, X, Moon, Sun } from 'lucide-react'
import { TrackIdSearch } from './TrackIdSearch'
import { Footer } from './Footer'
import { useAuth } from '../../lib/auth'
import { cn } from '../../lib/utils'

export function PublicLayout() {
  const { t, i18n } = useTranslation()
  const { role } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const [signinOpen, setSigninOpen] = useState(false)
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  const navigate = useNavigate()

  const langs = [{ code: 'en', label: 'English' }, { code: 'hi', label: 'हिन्दी' }]

  const toggleDark = () => {
    const next = !dark
    setDark(next)
    document.documentElement.classList.toggle('dark', next)
    localStorage.setItem('cr_theme', next ? 'dark' : 'light')
  }

  const dashTo = role === 'admin' ? '/dashboard' : role === 'official' ? '/dashboard' : '/dashboard'

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--surface)]/85 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2 shrink-0" aria-label="CrowdResolve home">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-teal-brand-600 font-display text-lg font-bold text-white">C</div>
            <span className="font-display text-lg font-bold text-[var(--text)] hidden xs:inline sm:inline">CrowdResolve</span>
          </Link>

          {/* center track search */}
          <div className="hidden flex-1 max-w-md mx-auto md:block">
            <TrackIdSearch compact />
          </div>

          <nav className="ml-auto flex items-center gap-1.5" aria-label="Primary">
            <div className="hidden items-center rounded-lg border border-[var(--border)] p-0.5 sm:flex" role="group" aria-label={t('topbar.language')}>
              <Globe className="mx-1.5 h-3.5 w-3.5 text-[var(--text-faint)]" />
              {langs.map((l) => (
                <button key={l.code} onClick={() => void i18n.changeLanguage(l.code)}
                  className={cn('rounded-md px-2 py-1 text-[11px] font-bold',
                    i18n.language?.startsWith(l.code) ? 'bg-brand-600 text-white' : 'text-[var(--text-muted)]')}
                  aria-pressed={i18n.language?.startsWith(l.code)}>{l.label}</button>
              ))}
            </div>
            <button onClick={toggleDark} className="rounded-lg p-2 text-[var(--text-muted)] hover:bg-[var(--surface-2)]" aria-label={t('topbar.theme')}>
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>

            {/* sign-in dropdown */}
            <div className="relative">
              <button onClick={() => setSigninOpen((v) => !v)}
                className="flex items-center gap-1.5 rounded-xl bg-brand-600 px-3.5 py-2 text-sm font-semibold text-white hover:bg-brand-700 transition-colors"
                aria-haspopup="menu" aria-expanded={signinOpen}>
                {role ? t('nav.dashboard') : t('topbar.signIn')} <ChevronDown className="h-3.5 w-3.5" />
              </button>
              {signinOpen && (
                <div className="absolute right-0 mt-2 w-52 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-1.5 shadow-[var(--shadow-pop)]" role="menu">
                  {role ? (
                    <button onClick={() => { setSigninOpen(false); navigate(dashTo) }} className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-2)]">{t('nav.dashboard')}</button>
                  ) : (
                    <>
                      <MenuItem to="/login/citizen" label={t('auth.signInCitizen')} onClick={() => setSigninOpen(false)} />
                      <MenuItem to="/login/official" label={t('auth.signInOfficial')} onClick={() => setSigninOpen(false)} />
                      <MenuItem to="/admin/login" label={t('footer.adminLogin')} subtle onClick={() => setSigninOpen(false)} />
                    </>
                  )}
                </div>
              )}
            </div>

            <button className="rounded-lg p-2 text-[var(--text-muted)] hover:bg-[var(--surface-2)] md:hidden" onClick={() => setMenuOpen((v) => !v)} aria-label="Menu" aria-expanded={menuOpen}>
              {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </nav>
        </div>

        {/* mobile track search */}
        <div className="border-t border-[var(--border)] px-4 py-2 md:hidden">
          <TrackIdSearch compact />
        </div>

        {/* mobile menu */}
        {menuOpen && (
          <nav className="border-t border-[var(--border)] bg-[var(--surface)] px-4 py-3 md:hidden" aria-label="Mobile">
            <MobileLink to="/" onClick={() => setMenuOpen(false)}>{t('footer.home')}</MobileLink>
            <MobileLink to="/complaint/new" onClick={() => setMenuOpen(false)}>{t('nav.fileComplaint')}</MobileLink>
            <MobileLink to="/about" onClick={() => setMenuOpen(false)}>{t('footer.aboutUs')}</MobileLink>
            <MobileLink to="/faqs" onClick={() => setMenuOpen(false)}>{t('footer.faqs')}</MobileLink>
            <MobileLink to="/login/citizen" onClick={() => setMenuOpen(false)}>{t('auth.signInCitizen')}</MobileLink>
            <MobileLink to="/login/official" onClick={() => setMenuOpen(false)}>{t('auth.signInOfficial')}</MobileLink>
            <MobileLink to="/admin/login" onClick={() => setMenuOpen(false)} subtle>{t('footer.adminLogin')}</MobileLink>
          </nav>
        )}
      </header>

      <main className="flex-1">
        <Outlet />
      </main>
      <Footer />
    </div>
  )
}

function MenuItem({ label, onClick, subtle }: { to: string; label: string; onClick: () => void; subtle?: boolean }) {
  return (
    <button onClick={onClick}
      className={cn('block w-full rounded-lg px-3 py-2 text-left text-sm transition-colors',
        subtle ? 'text-[var(--text-muted)] hover:bg-[var(--surface-2)]' : 'font-medium text-[var(--text)] hover:bg-brand-50 dark:hover:bg-brand-900/20')}>
      {label}
    </button>
  )
}

function MobileLink({ to, children, onClick, subtle }: { to: string; children: React.ReactNode; onClick: () => void; subtle?: boolean }) {
  return (
    <NavLink to={to} onClick={onClick} end={to === '/'}
      className={({ isActive }) => cn('block rounded-lg px-3 py-2.5 text-sm font-medium',
        isActive && !subtle ? 'text-brand-700 dark:text-brand-300' : subtle ? 'text-[var(--text-faint)]' : 'text-[var(--text)]')}>
      {children}
    </NavLink>
  )
}
