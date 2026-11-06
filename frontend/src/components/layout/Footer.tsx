import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Mail, Phone, MapPin, Clock, ArrowUp, AlertTriangle, Globe,
} from 'lucide-react'

// lucide-react no longer ships brand icons — minimal inline SVGs instead
const svg = (d: string) => (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4" {...props}><path d={d} /></svg>
)
const BrandX = svg('M18.9 1.15h3.68l-8.04 9.19L24 22.85h-7.41l-5.8-7.58-6.64 7.58H.47l8.6-9.83L0 1.15h7.59l5.24 6.93 6.07-6.93Zm-1.29 19.5h2.04L6.49 3.24H4.3l13.31 17.41Z')
const BrandInstagram = svg('M12 2.16c3.2 0 3.58.01 4.85.07 1.17.05 1.8.25 2.23.41.56.22.96.48 1.38.9.42.42.68.82.9 1.38.16.42.36 1.06.41 2.23.06 1.27.07 1.65.07 4.85s-.01 3.58-.07 4.85c-.05 1.17-.25 1.8-.41 2.23-.22.56-.48.96-.9 1.38-.42.42-.82.68-1.38.9-.42.16-1.06.36-2.23.41-1.27.06-1.65.07-4.85.07s-3.58-.01-4.85-.07c-1.17-.05-1.8-.25-2.23-.41-.56-.22-.96-.48-1.38-.9-.42-.42-.68-.82-.9-1.38-.16-.42-.36-1.06-.41-2.23-.06-1.27-.07-1.65-.07-4.85s.01-3.58.07-4.85c.05-1.17.25-1.8.41-2.23.22-.56.48-.96.9-1.38.42-.42.82-.68 1.38-.9.42-.16 1.06-.36 2.23-.41 1.27-.06 1.65-.07 4.85-.07Zm0 3.68a6.16 6.16 0 1 0 0 12.32 6.16 6.16 0 0 0 0-12.32Zm0 10.16a4 4 0 1 1 0-8 4 4 0 0 1 0 8Zm7.85-10.4a1.44 1.44 0 1 1-2.88 0 1.44 1.44 0 0 1 2.88 0Z')
const BrandFacebook = svg('M24 12.07C24 5.4 18.63 0 12 0S0 5.4 0 12.07C0 18.1 4.39 23.09 10.13 24v-8.44H7.08v-3.49h3.05V9.41c0-3.02 1.79-4.7 4.53-4.7 1.31 0 2.68.24 2.68.24v2.97h-1.51c-1.49 0-1.95.93-1.95 1.89v2.26h3.32l-.53 3.49h-2.79V24C19.61 23.09 24 18.1 24 12.07Z')
const BrandLinkedIn = svg('M20.45 20.45h-3.55v-5.57c0-1.33-.03-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.47-.9 1.63-1.85 3.36-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28ZM5.34 7.43a2.06 2.06 0 1 1 0-4.12 2.06 2.06 0 0 1 0 4.12ZM7.12 20.45H3.55V9h3.57v11.45ZM22.22 0H1.77C.79 0 0 .77 0 1.72v20.55C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.72C24 .77 23.2 0 22.22 0Z')
const BrandYouTube = svg('M23.5 6.19a3.02 3.02 0 0 0-2.12-2.14C19.5 3.55 12 3.55 12 3.55s-7.5 0-9.38.5A3.02 3.02 0 0 0 .5 6.19C0 8.07 0 12 0 12s0 3.93.5 5.81a3.02 3.02 0 0 0 2.12 2.14c1.88.5 9.38.5 9.38.5s7.5 0 9.38-.5a3.02 3.02 0 0 0 2.12-2.14C24 15.93 24 12 24 12s0-3.93-.5-5.81ZM9.55 15.57V8.43L15.82 12l-6.27 3.57Z')
const BrandGitHub = svg('M12 .3a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58v-2.03c-3.34.73-4.04-1.61-4.04-1.61-.55-1.39-1.34-1.76-1.34-1.76-1.08-.74.08-.73.08-.73 1.2.08 1.84 1.23 1.84 1.23 1.07 1.83 2.81 1.3 3.5 1 .1-.78.42-1.31.76-1.61-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.13-.3-.54-1.52.11-3.18 0 0 1-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.28-1.55 3.29-1.23 3.29-1.23.66 1.66.25 2.88.12 3.18.77.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.63-5.49 5.92.43.37.81 1.1.81 2.22v3.29c0 .32.21.7.82.58A12 12 0 0 0 12 .3Z')
import { Button, Input } from '../ui/primitives'
import { TrackIdSearch } from './TrackIdSearch'
import { cn } from '../../lib/utils'

const SOCIALS = [
  { icon: BrandX, label: 'X (Twitter)', href: 'https://x.com' },
  { icon: BrandInstagram, label: 'Instagram', href: 'https://instagram.com' },
  { icon: BrandFacebook, label: 'Facebook', href: 'https://facebook.com' },
  { icon: BrandLinkedIn, label: 'LinkedIn', href: 'https://linkedin.com' },
  { icon: BrandYouTube, label: 'YouTube', href: 'https://youtube.com' },
  { icon: BrandGitHub, label: 'GitHub', href: 'https://github.com' },
]

function FooterCol({ title, links }: { title: string; links: { label: string; to: string }[] }) {
  return (
    <div>
      <h4 className="font-display text-sm font-semibold text-[var(--text)] mb-3">{title}</h4>
      <ul className="space-y-2">
        {links.map((l) => (
          <li key={l.to + l.label}>
            <Link to={l.to} className="text-sm text-[var(--text-muted)] hover:text-brand-600 transition-colors">
              {l.label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function Footer() {
  const { t, i18n } = useTranslation()
  const year = new Date().getFullYear()
  const [email, setEmail] = useState('')
  const [subscribed, setSubscribed] = useState(false)

  const langs = [
    { code: 'en', label: 'English' },
    { code: 'hi', label: 'हिन्दी' },
  ]

  return (
    <footer className="mt-16 border-t border-[var(--border)] bg-[var(--surface)]">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 py-12">
        <div className="grid gap-10 md:grid-cols-2 lg:grid-cols-6">
          {/* brand */}
          <div className="lg:col-span-2">
            <Link to="/" className="flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-teal-brand-600 text-white font-display font-bold">C</div>
              <span className="font-display text-lg font-bold text-[var(--text)]">CrowdResolve</span>
            </Link>
            <p className="mt-3 text-sm font-medium text-brand-700 dark:text-brand-300">{t('app.tagline')}</p>
            <p className="mt-2 text-xs text-[var(--text-muted)] max-w-xs">{t('app.mission')}</p>
            <div className="mt-4 flex gap-2">
              {SOCIALS.map(({ icon: Icon, label, href }) => (
                <a key={label} href={href} target="_blank" rel="noopener noreferrer" aria-label={label}
                  className="flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-brand-600 hover:border-brand-300 transition-colors">
                  <Icon className="h-4 w-4" />
                </a>
              ))}
            </div>
            {/* newsletter */}
            <form className="mt-5" onSubmit={(e) => { e.preventDefault(); if (email) setSubscribed(true) }}>
              <label className="text-xs font-semibold text-[var(--text-muted)]">{t('footer.newsletter')}</label>
              {subscribed ? (
                <p className="mt-2 text-sm text-brand-600">✓ {t('footer.subscribe')}</p>
              ) : (
                <div className="mt-1.5 flex gap-2">
                  <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                    placeholder={t('footer.newsletterPlaceholder')} className="h-9 text-xs" aria-label={t('footer.newsletter')} />
                  <Button size="sm" type="submit" className="h-9">{t('footer.subscribe')}</Button>
                </div>
              )}
            </form>
          </div>

          <FooterCol title={t('footer.quickLinks')} links={[
            { label: t('footer.home'), to: '/' },
            { label: t('nav.fileComplaint'), to: '/complaint/new' },
            { label: t('topbar.trackLabel'), to: '/#track' },
            { label: t('footer.howItWorks'), to: '/#how' },
            { label: t('footer.aboutUs'), to: '/about' },
            { label: t('footer.faqs'), to: '/faqs' },
          ]} />
          <FooterCol title={t('footer.forCitizens')} links={[
            { label: t('footer.guidelines'), to: '/guidelines' },
            { label: t('footer.categories'), to: '/categories' },
            { label: t('footer.timelines'), to: '/timelines' },
            { label: t('footer.citizenCharter'), to: '/citizen-charter' },
            { label: t('footer.successStories'), to: '/success-stories' },
          ]} />
          <FooterCol title={t('footer.forGovernment')} links={[
            { label: t('footer.officialSignIn'), to: '/login/official' },
            { label: t('footer.requestAccess'), to: '/request-access' },
            { label: t('footer.departments'), to: '/departments' },
            { label: t('footer.resources'), to: '/resources' },
          ]} />
          <FooterCol title={t('footer.legal')} links={[
            { label: t('footer.privacy'), to: '/privacy' },
            { label: t('footer.terms'), to: '/terms' },
            { label: t('footer.accessibility'), to: '/accessibility' },
            { label: t('footer.disclaimer'), to: '/disclaimer' },
            { label: t('footer.contactUs'), to: '/contact' },
            { label: t('footer.adminLogin'), to: '/admin/login' },
          ]} />
        </div>

        {/* contact strip */}
        <div className="mt-10 grid gap-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)]/50 p-5 sm:grid-cols-2 lg:grid-cols-4">
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]"><Phone className="h-4 w-4 text-brand-600" /> {t('footer.helpline')}: 1800-XXX-XXXX</div>
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]"><Mail className="h-4 w-4 text-brand-600" /> {t('footer.email')}</div>
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]"><MapPin className="h-4 w-4 text-brand-600" /> {t('footer.address')}</div>
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]"><Clock className="h-4 w-4 text-brand-600" /> {t('footer.hours')}</div>
        </div>
        <div className="mt-3 flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {t('footer.emergency')}
        </div>

        {/* mini track search + language */}
        <div className="mt-8 flex flex-col gap-4 border-t border-[var(--border)] pt-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="w-full sm:max-w-sm">
            <TrackIdSearch compact />
          </div>
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-[var(--text-muted)]" />
            <div className="flex rounded-lg border border-[var(--border)] p-0.5" role="group" aria-label={t('topbar.language')}>
              {langs.map((l) => (
                <button key={l.code} onClick={() => void i18n.changeLanguage(l.code)}
                  className={cn('rounded-md px-2.5 py-1 text-xs font-semibold transition-colors',
                    i18n.language?.startsWith(l.code) ? 'bg-brand-600 text-white' : 'text-[var(--text-muted)] hover:text-[var(--text)]')}
                  aria-pressed={i18n.language?.startsWith(l.code)}>
                  {l.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* bottom bar */}
        <div className="mt-8 flex flex-col items-center justify-between gap-3 border-t border-[var(--border)] pt-6 text-xs text-[var(--text-faint)] sm:flex-row">
          <p>{t('footer.rights', { year })} · {t('footer.builtFor')}</p>
          <p>{t('footer.osm')} · {t('footer.leaflet')}</p>
          <button onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            className="inline-flex items-center gap-1 hover:text-brand-600 transition-colors" aria-label={t('footer.backToTop')}>
            {t('footer.backToTop')} <ArrowUp className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </footer>
  )
}
