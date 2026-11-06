import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Search, Loader2 } from 'lucide-react'
import { normalizeTrackingId } from '../../lib/trackingId'
import { cn } from '../../lib/utils'
import { Input } from '../ui/primitives'

/**
 * Global "Track your complaint" search — used in header, dashboards, hero, footer.
 * Validates the ID client-side, then routes to /track/:id.
 */
export function TrackIdSearch({ compact = false, large = false, className }: { compact?: boolean; large?: boolean; className?: string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault()
    const res = normalizeTrackingId(value)
    if (!res.ok) {
      setError(t('track.invalidId'))
      return
    }
    setError(null)
    setBusy(true)
    // brief tick so the loading affordance is visible; navigation is instant
    navigate(`/track/${encodeURIComponent(res.id)}`)
    setBusy(false)
  }

  return (
    <form onSubmit={submit} className={cn('w-full', className)} noValidate>
      <div className={cn('flex items-center gap-2 rounded-2xl border bg-[var(--surface)] transition-colors',
        error ? 'border-red-400' : 'border-[var(--border)] focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-500/20',
        large ? 'p-2' : 'p-1')}>
        <Search className={cn('ml-2 shrink-0 text-[var(--text-faint)]', large ? 'h-5 w-5' : 'h-4 w-4')} aria-hidden />
        <Input
          value={value}
          onChange={(e) => { setValue(e.target.value.toUpperCase()); setError(null) }}
          onPaste={(e) => {
            // accept pasted IDs with or without dashes/spaces
            const text = e.clipboardData.getData('text')
            if (/^[\w\- ]{6,}$/.test(text)) {
              e.preventDefault()
              setValue(text.trim().toUpperCase())
            }
          }}
          placeholder={t('track.placeholder')}
          aria-label={t('topbar.trackLabel')}
          className={cn('border-0 bg-transparent focus:ring-0', large ? 'h-12 text-base' : compact ? 'h-8 text-xs' : 'h-9 text-sm')}
          inputMode="text"
          autoComplete="off"
        />
        <button type="submit" disabled={busy}
          className={cn('shrink-0 rounded-xl font-semibold text-white transition-colors bg-brand-600 hover:bg-brand-700 disabled:opacity-60',
            large ? 'px-5 py-2.5 text-sm' : 'px-3 py-1.5 text-xs')}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : t('topbar.trackSearch')}
        </button>
      </div>
      {error && <p className="mt-1.5 text-xs text-red-500" role="alert">{error}</p>}
    </form>
  )
}
