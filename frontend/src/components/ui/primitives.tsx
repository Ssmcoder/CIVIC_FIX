import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/utils'
import { useTranslation } from 'react-i18next'
import { Inbox, Loader2 } from 'lucide-react'

/* ------------------------------------------------------------- Button */
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 font-medium rounded-xl transition-all duration-150 ' +
  'focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50 disabled:pointer-events-none ' +
  'active:scale-[0.98] select-none',
  {
    variants: {
      variant: {
        primary: 'bg-brand-600 text-white hover:bg-brand-700 shadow-sm shadow-brand-600/20',
        secondary: 'bg-[var(--surface-2)] text-[var(--text)] hover:bg-[var(--border)] border border-[var(--border)]',
        outline: 'border border-brand-600 text-brand-700 hover:bg-brand-50 dark:text-brand-300 dark:hover:bg-brand-900/30',
        ghost: 'text-[var(--text-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--text)]',
        danger: 'bg-red-600 text-white hover:bg-red-700',
        teal: 'bg-teal-brand-600 text-white hover:bg-teal-brand-700',
      },
      size: {
        sm: 'h-8 px-3 text-sm',
        md: 'h-10 px-4 text-sm',
        lg: 'h-12 px-6 text-base',
        icon: 'h-9 w-9',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  ),
)
Button.displayName = 'Button'

/* --------------------------------------------------------------- Card */
export function Card({ className, children, ...props }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('card p-5', className)} {...props}>{children}</div>
}

export function CardHeader({ title, subtitle, action }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 mb-4">
      <div>
        <h3 className="font-display font-semibold text-[var(--text)]">{title}</h3>
        {subtitle && <p className="text-sm text-[var(--text-muted)] mt-0.5">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

/* -------------------------------------------------------------- Inputs */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        'h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 text-sm text-[var(--text)]',
        'placeholder:text-[var(--text-faint)] transition-colors',
        'focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20',
        'disabled:opacity-50',
        className,
      )}
      {...props}
    />
  ),
)
Input.displayName = 'Input'

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        'w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 py-2.5 text-sm text-[var(--text)]',
        'placeholder:text-[var(--text-faint)] transition-colors resize-y min-h-[96px]',
        'focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20',
        className,
      )}
      {...props}
    />
  ),
)
Textarea.displayName = 'Textarea'

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        'h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 text-sm text-[var(--text)]',
        'focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20',
        className,
      )}
      {...props}
    >{children}</select>
  ),
)
Select.displayName = 'Select'

export function Field({ label, error, hint, children, required }: { label: string; error?: string; hint?: string; children: ReactNode; required?: boolean }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-[var(--text)]">
        {label}{required && <span className="text-red-500 ml-0.5" aria-hidden>*</span>}
      </span>
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-[var(--text-muted)]">{hint}</span>}
      {error && <span className="mt-1 block text-xs text-red-500" role="alert">{error}</span>}
    </label>
  )
}

/* -------------------------------------------------------------- Badges */
const statusTones: Record<string, string> = {
  // semantic groups
  registered: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
  review: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  progress: 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
  verify: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300',
  resolved: 'bg-brand-100 text-brand-700 dark:bg-brand-900/40 dark:text-brand-300',
  closed: 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
  reopened: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  open: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
}

export function StatusChip({ status, className }: { status: string; className?: string }) {
  const { t } = useTranslation()
  const key = status.toLowerCase()
  const tone =
    ['received', 'registered'].includes(key) ? 'registered'
    : ['under_review', 'inspection_scheduled'].includes(key) ? 'review'
    : ['in_progress', 'assigned'].includes(key) ? 'progress'
    : ['awaiting_verification'].includes(key) ? 'verify'
    : ['resolved', 'closed'].includes(key) ? 'resolved'
    : ['reopened'].includes(key) ? 'reopened'
    : 'open'
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold', statusTones[tone], className)}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {t(`status.${status}`, { defaultValue: status.replace(/_/g, ' ') })}
    </span>
  )
}

const severityTones: Record<string, string> = {
  low: 'bg-brand-100 text-brand-700 dark:bg-brand-900/40 dark:text-brand-300',
  medium: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  high: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
  critical: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
}

export function SeverityBadge({ severity, score, className }: { severity?: string | null; score?: number | null; className?: string }) {
  const { t } = useTranslation()
  const lvl = severity || (score != null && score >= 75 ? 'critical' : score != null && score >= 50 ? 'high' : score != null && score >= 25 ? 'medium' : 'low')
  return (
    <span className={cn('inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold', severityTones[lvl] || severityTones.low, className)}>
      {t(`severity.${lvl}`, { defaultValue: lvl })}{score != null ? ` · ${Math.round(score)}` : ''}
    </span>
  )
}

/* ----------------------------------------------------------- Feedback */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton', className)} aria-hidden />
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('h-5 w-5 animate-spin text-brand-600', className)} aria-label="loading" />
}

export function EmptyState({ title, body, action, icon }: { title: string; body?: string; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--surface-2)] text-[var(--text-faint)]">
        {icon || <Inbox className="h-7 w-7" />}
      </div>
      <div>
        <p className="font-display font-semibold text-[var(--text)]">{title}</p>
        {body && <p className="mt-1 text-sm text-[var(--text-muted)] max-w-sm">{body}</p>}
      </div>
      {action}
    </div>
  )
}

export function ErrorState({ title, body, onRetry }: { title?: string; body?: string; onRetry?: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-center" role="alert">
      <p className="font-display font-semibold text-red-600">{title || t('errors.generic')}</p>
      {body && <p className="text-sm text-[var(--text-muted)] max-w-sm">{body}</p>}
      {onRetry && <Button variant="outline" size="sm" onClick={onRetry}>{t('track.retry')}</Button>}
    </div>
  )
}

/* --------------------------------------------------------- Stat / Ring */
export function StatCard({ label, value, delta, spark, icon, hint }: {
  label: string; value: ReactNode; delta?: { value: string; positive?: boolean }; spark?: number[]; icon?: ReactNode; hint?: string
}) {
  const max = spark?.length ? Math.max(...spark, 1) : 1
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-[var(--text-muted)]">{label}</p>
          <p className="font-display text-3xl font-bold text-[var(--text)] mt-1">{value}</p>
          {delta && (
            <p className={cn('mt-1 text-xs font-semibold', delta.positive ? 'text-brand-600' : 'text-red-500')}>
              {delta.positive ? '▲' : '▼'} {delta.value}
            </p>
          )}
          {hint && <p className="mt-1 text-xs text-[var(--text-faint)]">{hint}</p>}
        </div>
        {icon && <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-900/30">{icon}</div>}
      </div>
      {spark && spark.length > 1 && (
        <div className="mt-4 flex h-10 items-end gap-1" aria-hidden>
          {spark.map((v, i) => (
            <div key={i} className="flex-1 rounded-t bg-brand-500/70 transition-all" style={{ height: `${Math.max(8, (v / max) * 100)}%` }} />
          ))}
        </div>
      )}
    </Card>
  )
}

export function RingProgress({ value, size = 120, stroke = 10, label, sub }: { value: number; size?: number; stroke?: number; label?: string; sub?: string }) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(100, value))
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }} role="img" aria-label={`${pct}%`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-2)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="url(#ringGrad)" strokeWidth={stroke}
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)} className="transition-all duration-700" />
        <defs>
          <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#10b981" />
            <stop offset="100%" stopColor="#0d9488" />
          </linearGradient>
        </defs>
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-display text-2xl font-bold text-[var(--text)]">{Math.round(pct)}%</span>
        {label && <span className="text-[11px] text-[var(--text-muted)]">{label}</span>}
        {sub && <span className="text-[10px] text-[var(--text-faint)]">{sub}</span>}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------- Misc */
export function Avatar({ name, className }: { name?: string; className?: string }) {
  const initials = (name || '?').split(' ').map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  return (
    <div className={cn('flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-teal-brand-600 text-xs font-bold text-white', className)}>
      {initials}
    </div>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--text-muted)]">{children}</kbd>
}
