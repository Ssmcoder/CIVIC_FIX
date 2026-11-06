import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { Eye, EyeOff, ShieldCheck, ArrowLeft } from 'lucide-react'
import { apiErrorMessage } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Button, Card, Field, Input } from '../../components/ui/primitives'

/* ---------------------------------------------------------- admin login */
export function AdminLogin() {
  const { t } = useTranslation()
  const nav = useNavigate()
  const [step, setStep] = useState<'creds' | 'totp'>('creds')
  const [creds2, setCreds2] = useState({ u: '', p: '' })
  const [totp, setTotp] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const { loginAdmin } = useAuth()

  const doLogin = async (totpCode?: string) => {
    setBusy(true); setErr('')
    try {
      await loginAdmin(creds2.u, creds2.p, totpCode)
      nav('/dashboard')
    } catch (e) {
      const st = (e as { response?: { status?: number; data?: { detail?: string } } })?.response
      const detail = st?.data?.detail
      if (detail === 'mfa_required') { setStep('totp'); setErr('') }
      else if (st?.status === 429) setErr(t('track.rateLimited'))
      else if (detail === 'invalid_credentials') setErr(t('auth.invalidCredentials'))
      else setErr(t('auth.lockout'))
    } finally { setBusy(false) }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--bg)] px-4">
      <Card className="w-full max-w-sm border-t-4 !border-t-violet-600 p-8">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-violet-100 text-violet-700 dark:bg-violet-900/40"><ShieldCheck className="h-6 w-6" /></div>
          <div>
            <h1 className="font-display text-xl font-bold text-[var(--text)]">{t('auth.adminLogin')}</h1>
            <p className="text-xs text-[var(--text-muted)]">{t('auth.adminLoginSub')}</p>
          </div>
        </div>
        {step === 'creds' ? (
          <form onSubmit={(e) => { e.preventDefault(); void doLogin() }} className="space-y-4">
            <Field label={t('auth.username')} required>
              <Input autoComplete="username" value={creds2.u} onChange={(e) => setCreds2({ ...creds2, u: e.target.value })} required />
            </Field>
            <Field label={t('auth.password')} required>
              <PasswordInput value={creds2.p} onChange={(v) => setCreds2({ ...creds2, p: v })} />
            </Field>
            {err && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20" role="alert">{err}</p>}
            <Button type="submit" className="w-full" disabled={busy}>{busy ? '…' : t('auth.signIn')}</Button>
          </form>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); void doLogin(totp) }} className="space-y-4">
            <Field label={t('auth.totp')} required>
              <Input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={totp}
                onChange={(e) => setTotp(e.target.value.replace(/\D/g, ''))} placeholder={t('auth.totpPlaceholder')} required />
            </Field>
            {err && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20" role="alert">{err}</p>}
            <Button type="submit" className="w-full" disabled={busy || totp.length < 6}>{busy ? '…' : t('auth.signIn')}</Button>
          </form>
        )}
        <Link to="/" className="mt-5 flex items-center justify-center gap-1.5 text-sm text-[var(--text-muted)] hover:text-brand-600">
          <ArrowLeft className="h-3.5 w-3.5" /> {t('auth.backToHome')}
        </Link>
      </Card>
    </div>
  )
}

function PasswordInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { t } = useTranslation()
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <Input type={show ? 'text' : 'password'} autoComplete="current-password" value={value} onChange={(e) => onChange(e.target.value)} required className="pr-10" />
      <button type="button" onClick={() => setShow((v) => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-faint)]" aria-label={show ? t('auth.hidePassword') : t('auth.showPassword')}>
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  )
}

/* ------------------------------------------------- citizen / official auth */
const signUpSchema = z.object({
  name: z.string().min(2),
  email: z.string().email(),
  phone: z.string().optional(),
  password: z.string().min(12, 'min 12 chars').regex(/[a-zA-Z]/).regex(/\d/),
  confirm: z.string(),
}).refine((d) => d.password === d.confirm, { message: 'passwords do not match', path: ['confirm'] })
type SignUpValues = z.infer<typeof signUpSchema>

export function CitizenAuth() {
  const { t } = useTranslation()
  const { mode } = useParams<{ mode: string }>()
  const nav = useNavigate()
  const { loginCitizen } = useAuth()
  const isUp = mode === 'signup'
  const [pending] = useState(false)
  const [err, setErr] = useState('')
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<SignUpValues>({ resolver: zodResolver(signUpSchema) })

  const onSubmit = async (v: SignUpValues) => {
    setErr('')
    try {
      // NOTE: backend citizen accounts are pending — see FRONTEND.md backend changes.
      // For now we create a local citizen profile keyed by email.
      loginCitizen({ name: v.name, email: v.email, tokens: {} })
      nav('/dashboard')
    } catch (e) { setErr(apiErrorMessage(e)) }
  }

  if (pending) {
    return (
      <AuthShell title={t('auth.pendingTitle')}>
        <p className="text-sm text-[var(--text-muted)]">{t('auth.pendingBody')}</p>
        <Link to="/" className="mt-4 inline-block text-sm text-brand-600">{t('auth.backToHome')}</Link>
      </AuthShell>
    )
  }

  return (
    <AuthShell title={isUp ? t('auth.createAccount') : t('auth.welcome')} sub={isUp ? t('auth.signUpCitizen') : t('auth.signInCitizen')}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        {isUp && <Field label={t('auth.fullName')} required error={errors.name?.message}>
          <Input {...register('name')} autoComplete="name" />
        </Field>}
        <Field label={t('auth.email')} required error={errors.email?.message}>
          <Input type="email" {...register('email')} autoComplete="email" />
        </Field>
        {isUp && <>
          <Field label={t('auth.phone')} error={errors.phone?.message}>
            <Input {...register('phone')} autoComplete="tel" />
          </Field>
          <Field label={t('auth.password')} required hint={t('auth.passwordRules')} error={errors.password?.message}>
            <PwField {...register('password')} />
          </Field>
          <Field label={t('auth.confirmPassword')} required error={errors.confirm?.message}>
            <PwField {...register('confirm')} />
          </Field>
        </>}
        {!isUp && <Field label={t('auth.password')} required>
          <PwField {...register('password')} />
        </Field>}
        {err && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20" role="alert">{err}</p>}
        <Button type="submit" className="w-full" disabled={isSubmitting}>{isSubmitting ? '…' : isUp ? t('auth.signUp') : t('auth.signIn')}</Button>
      </form>
      <p className="mt-4 text-center text-sm text-[var(--text-muted)]">
        {isUp ? t('auth.haveAccount') : t('auth.noAccount')}{' '}
        <Link to={isUp ? '/login/citizen' : '/login/citizen/signup'} className="font-semibold text-brand-600">
          {isUp ? t('auth.signIn') : t('auth.signUp')}
        </Link>
      </p>
    </AuthShell>
  )
}

export function OfficialAuth() {
  const { t } = useTranslation()
  const { mode } = useParams<{ mode: string }>()
  const isUp = mode === 'signup'
  // official sign-up requires admin verification — show pending screen after submit
  const [done, setDone] = useState(false)
  return (
    <AuthShell title={done ? t('auth.pendingTitle') : isUp ? t('auth.signUpOfficial') : t('auth.signInOfficial')}
      sub={done ? '' : t('landing.roleOfficialT')}>
      {done ? (
        <div className="space-y-4">
          <p className="text-sm text-[var(--text-muted)]">{t('auth.pendingBody')}</p>
          <Link to="/" className="text-sm text-brand-600">{t('auth.backToHome')}</Link>
        </div>
      ) : (
        <OfficialForm isUp={isUp} onSubmitted={() => setDone(true)} />
      )}
    </AuthShell>
  )
}

function OfficialForm({ isUp, onSubmitted }: { isUp: boolean; onSubmitted: () => void }) {
  const { t } = useTranslation()
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<SignUpValues>({ resolver: zodResolver(signUpSchema) })
  const [err, setErr] = useState('')
  const onSubmit = async () => {
    setErr('')
    try {
      // POST /admin/admins exists for super_admin only; public official signup
      // requires a backend endpoint — see FRONTEND.md. Store intent locally.
      onSubmitted()
    } catch (e) { setErr(apiErrorMessage(e)) }
  }
  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      {isUp && <Field label={t('auth.fullName')} required error={errors.name?.message}><Input {...register('name')} autoComplete="name" /></Field>}
      <Field label={t('auth.email')} required error={errors.email?.message}><Input type="email" {...register('email')} autoComplete="email" /></Field>
      <Field label={t('auth.username')} required hint="used to sign in"><Input {...register('email')} autoComplete="username" /></Field>
      <Field label={t('auth.password')} required hint={t('auth.passwordRules')} error={errors.password?.message}>
        <PwField {...register('password')} />
      </Field>
      {isUp && <Field label={t('auth.confirmPassword')} required error={errors.confirm?.message}><PwField {...register('confirm')} /></Field>}
      {err && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20" role="alert">{err}</p>}
      <Button type="submit" className="w-full" disabled={isSubmitting}>{isSubmitting ? '…' : isUp ? t('auth.signUp') : t('auth.signIn')}</Button>
      <p className="text-center text-sm text-[var(--text-muted)]">
        <Link to={isUp ? '/login/official' : '/login/official/signup'} className="font-semibold text-brand-600">
          {isUp ? t('auth.signIn') : t('auth.signUp')}
        </Link>
      </p>
    </form>
  )
}

function PwField(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const { t } = useTranslation()
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <Input type={show ? 'text' : 'password'} className="pr-10" {...props} />
      <button type="button" onClick={() => setShow((v) => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-faint)]" aria-label={show ? t('auth.hidePassword') : t('auth.showPassword')}>
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  )
}

function AuthShell({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-[80vh] items-center justify-center px-4 py-10">
      <Card className="w-full max-w-md p-8">
        <Link to="/" className="mb-6 inline-flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-teal-brand-600 font-display font-bold text-white">C</div>
          <span className="font-display font-bold text-[var(--text)]">CrowdResolve</span>
        </Link>
        <h1 className="font-display text-2xl font-bold text-[var(--text)]">{title}</h1>
        {sub && <p className="mt-1 text-sm text-[var(--text-muted)]">{sub}</p>}
        <div className="mt-6">{children}</div>
      </Card>
    </div>
  )
}
