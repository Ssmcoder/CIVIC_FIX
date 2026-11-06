import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { FileText, Sparkles, Building2, SearchCheck, ArrowRight, ChevronDown, ShieldCheck, MessageSquare, MapPin, CheckCircle2 } from 'lucide-react'
import { TrackIdSearch } from '../components/layout/TrackIdSearch'
import { Button, Card } from '../components/ui/primitives'
import { cn } from '../lib/utils'

function Counter({ to, suffix = '', decimals = 0 }: { to: number; suffix?: string; decimals?: number }) {
  const [v, setV] = useState(0)
  const ref = useRef<HTMLSpanElement>(null)
  const started = useRef(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const obs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && !started.current) {
        started.current = true
        const t0 = performance.now()
        const tick = (now: number) => {
          const p = Math.min(1, (now - t0) / 1400)
          setV(to * (1 - Math.pow(1 - p, 3)))
          if (p < 1) requestAnimationFrame(tick)
        }
        requestAnimationFrame(tick)
      }
    }, { threshold: 0.4 })
    obs.observe(el)
    return () => obs.disconnect()
  }, [to])
  return <span ref={ref}>{v.toLocaleString(undefined, { maximumFractionDigits: decimals, minimumFractionDigits: decimals })}{suffix}</span>
}

const FAQS = [
  { q: 'Do I need an account to file a complaint?', a: 'No. Anyone can file a complaint anonymously. You only need the Complaint ID we show you to track it.' },
  { q: 'How is priority decided?', a: 'Priority is computed from severity, public-safety risk, number of independent reports, waiting time and infrastructure vulnerability — every factor is shown, nothing is hidden.' },
  { q: 'What if my complaint is a duplicate?', a: 'Our AI groups similar complaints nearby into one incident. You can upvote the existing complaint instead of filing a new one.' },
  { q: 'How do I track my complaint?', a: 'Use the Track ID search with the Complaint ID (e.g. CR-2611-A7K9Q2) shown when you file. No login needed.' },
  { q: 'What happens after resolution?', a: 'The department uploads proof of work. You can confirm the fix or reopen the complaint if the problem persists.' },
]

export function Landing() {
  const { t } = useTranslation()
  const [openFaq, setOpenFaq] = useState<number | null>(0)

  const how = [
    { icon: FileText, title: t('landing.how1t'), desc: t('landing.how1d') },
    { icon: Sparkles, title: t('landing.how2t'), desc: t('landing.how2d') },
    { icon: Building2, title: t('landing.how3t'), desc: t('landing.how3d') },
    { icon: SearchCheck, title: t('landing.how4t'), desc: t('landing.how4d') },
  ]

  const roles = [
    { to: '/login/citizen', title: t('landing.roleCitizenT'), desc: t('landing.roleCitizenD'), icon: MessageSquare, cta: t('auth.signInCitizen'), lite: false },
    { to: '/login/official', title: t('landing.roleOfficialT'), desc: t('landing.roleOfficialD'), icon: Building2, cta: t('auth.signInOfficial'), lite: false },
    { to: '/admin/login', title: t('landing.roleAdminT'), desc: t('landing.roleAdminD'), icon: ShieldCheck, cta: t('footer.adminLogin'), lite: true },
  ]

  return (
    <div>
      {/* HERO */}
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_60%_at_50%_0%,rgba(16,185,129,0.12),transparent),radial-gradient(40%_40%_at_80%_20%,rgba(13,148,136,0.10),transparent)]" />
        <div className="relative mx-auto max-w-5xl px-4 pt-16 pb-14 text-center sm:px-6 sm:pt-24">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700 dark:border-brand-800 dark:bg-brand-900/30 dark:text-brand-300">
            <CheckCircle2 className="h-3.5 w-3.5" /> {t('landing.how2t')}: AI triage · dedup · transparent priority
          </span>
          <h1 className="font-display mt-5 text-4xl font-extrabold tracking-tight text-[var(--text)] sm:text-6xl">
            {t('landing.heroTitle')}
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-base text-[var(--text-muted)] sm:text-lg">
            {t('landing.heroSubtitle')}
          </p>

          <div className="mx-auto mt-8 max-w-xl">
            <TrackIdSearch large />
          </div>

          {/* live stats */}
          <div className="mx-auto mt-10 grid max-w-3xl grid-cols-1 gap-3 sm:grid-cols-3">
            {[
              { label: t('landing.statComplaints'), value: 12847, suffix: '+' },
              { label: t('landing.statResolved'), value: 9231, suffix: '+' },
              { label: t('landing.statAvgTime'), value: 4.2, suffix: 'd', decimals: 1 },
            ].map((s) => (
              <Card key={s.label} className="!p-4 text-center">
                <p className="font-display text-2xl font-bold text-brand-600"><Counter to={s.value} suffix={s.suffix} decimals={s.decimals ?? 0} /></p>
                <p className="mt-1 text-xs text-[var(--text-muted)]">{s.label}</p>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how" className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
        <h2 className="font-display text-center text-2xl font-bold text-[var(--text)] sm:text-3xl">{t('landing.howTitle')}</h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {how.map((h, i) => (
            <Card key={i} className="relative overflow-hidden p-5">
              <span className="absolute right-3 top-3 font-display text-4xl font-extrabold text-[var(--surface-2)]">{i + 1}</span>
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-900/30">
                <h.icon className="h-5 w-5" />
              </div>
              <h3 className="font-display mt-3 font-semibold text-[var(--text)]">{h.title}</h3>
              <p className="mt-1.5 text-sm text-[var(--text-muted)]">{h.desc}</p>
            </Card>
          ))}
        </div>
      </section>

      {/* ROLE CARDS */}
      <section className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
        <h2 className="font-display text-center text-2xl font-bold text-[var(--text)] sm:text-3xl">{t('landing.rolesTitle')}</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {roles.map((r) => (
            <Card key={r.title} className={cn('flex flex-col p-6', r.lite && 'border-dashed opacity-90')}>
              {r.lite && <span className="mb-3 w-fit rounded-full bg-[var(--surface-2)] px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-[var(--text-muted)]">{t('landing.roleAdminD').split('.')[0]}…</span>}
              <div className={cn('flex h-12 w-12 items-center justify-center rounded-2xl',
                r.lite ? 'bg-[var(--surface-2)] text-[var(--text-muted)]' : 'bg-gradient-to-br from-brand-500 to-teal-brand-600 text-white')}>
                <r.icon className="h-6 w-6" />
              </div>
              <h3 className="font-display mt-4 text-lg font-bold text-[var(--text)]">{r.title}</h3>
              <p className="mt-2 flex-1 text-sm text-[var(--text-muted)]">{r.desc}</p>
              <Link to={r.to} className="mt-5">
                <Button variant={r.lite ? 'secondary' : 'primary'} className="w-full">{r.cta} <ArrowRight className="h-4 w-4" /></Button>
              </Link>
            </Card>
          ))}
        </div>
      </section>

      {/* CTA strip */}
      <section className="mx-auto max-w-6xl px-4 pb-16 sm:px-6">
        <Card className="flex flex-col items-center gap-4 bg-gradient-to-r from-brand-600 to-teal-brand-700 p-8 text-center text-white sm:flex-row sm:justify-between sm:text-left">
          <div>
            <h3 className="font-display text-xl font-bold">{t('landing.fileNow')}</h3>
            <p className="mt-1 text-sm text-white/80 flex items-center gap-1.5"><MapPin className="h-4 w-4" /> {t('complaint.locationTitle')}: GPS · pin · address</p>
          </div>
          <Link to="/complaint/new"><Button variant="secondary" size="lg" className="!bg-white !text-brand-700 hover:!bg-brand-50">{t('landing.fileNow')}</Button></Link>
        </Card>
      </section>

      {/* FAQ + ABOUT */}
      <section className="mx-auto max-w-4xl px-4 pb-20 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-2">
          <div>
            <h2 className="font-display text-2xl font-bold text-[var(--text)]">{t('landing.faqTitle')}</h2>
            <div className="mt-5 space-y-2">
              {FAQS.map((f, i) => (
                <div key={i} className="card overflow-hidden !rounded-xl">
                  <button onClick={() => setOpenFaq(openFaq === i ? null : i)}
                    className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left text-sm font-semibold text-[var(--text)]"
                    aria-expanded={openFaq === i}>
                    {f.q}
                    <ChevronDown className={cn('h-4 w-4 shrink-0 text-[var(--text-faint)] transition-transform', openFaq === i && 'rotate-180')} />
                  </button>
                  {openFaq === i && <p className="px-4 pb-4 text-sm text-[var(--text-muted)]">{f.a}</p>}
                </div>
              ))}
            </div>
          </div>
          <div>
            <h2 className="font-display text-2xl font-bold text-[var(--text)]">{t('landing.aboutTitle')}</h2>
            <Card className="mt-5 p-6">
              <p className="text-sm leading-relaxed text-[var(--text-muted)]">{t('landing.aboutBody')}</p>
              <ul className="mt-4 space-y-2 text-sm text-[var(--text)]">
                {['AI classification & duplicate grouping', 'Explainable priority scoring', 'Leaflet + OpenStreetMap live location', 'SLA accountability dashboards'].map((x) => (
                  <li key={x} className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-brand-600" /> {x}</li>
                ))}
              </ul>
            </Card>
          </div>
        </div>
      </section>
    </div>
  )
}
