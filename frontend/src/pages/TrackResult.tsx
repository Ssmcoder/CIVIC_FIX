import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import {
  Copy, Check, Share2, Download, Bell, MapPin, Calendar, Building2, Tag, RefreshCw,
} from 'lucide-react'
import { complaintsApi } from '../lib/api'
import { useAuth } from '../lib/auth'
import { normalizeTrackingId } from '../lib/trackingId'
import { Button, Card, CardHeader, StatusChip, SeverityBadge, Skeleton, EmptyState, ErrorState } from '../components/ui/primitives'
import { TrackIdSearch } from '../components/layout/TrackIdSearch'
import { cn, formatDate, formatDateTime } from '../lib/utils'

const TIMELINE = ['received', 'under_review', 'in_progress', 'awaiting_verification', 'resolved']

function timelineIndex(status: string): number {
  const order = ['received', 'under_review', 'inspection_scheduled', 'in_progress', 'awaiting_verification', 'resolved', 'closed']
  const i = order.indexOf(status)
  if (i < 0) return 0
  // compress inspection into under_review step for the 5-step display
  return Math.min(4, i >= 4 ? i - 1 : i)
}

export function TrackResult() {
  const { t } = useTranslation()
  const { trackingId } = useParams<{ trackingId: string }>()
  const [params] = useSearchParams()
  const { citizen, saveTrackingToken, trackingTokenFor } = useAuth()
  const [secret, setSecret] = useState(params.get('secret') || '')
  const [copied, setCopied] = useState(false)
  const [notified, setNotified] = useState(false)

  const parsed = useMemo(() => normalizeTrackingId(decodeURIComponent(trackingId || '')), [trackingId])
  const publicId = parsed.ok && !parsed.isSecret ? parsed.id : null
  const directToken = parsed.ok && parsed.isSecret ? parsed.id : null

  // resolve the tracking secret: URL secret > saved citizen token > manual entry
  const token = useMemo(() => {
    if (directToken) return directToken
    if (secret) return secret
    if (publicId) return trackingTokenFor(publicId)
    return undefined
  }, [directToken, secret, publicId, trackingTokenFor])

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['track', token],
    queryFn: () => complaintsApi.track(token!),
    enabled: !!token,
    refetchInterval: 30000, // live-ish polling for status updates
    retry: 1,
  })

  const statusCode = (error as { response?: { status?: number } })?.response?.status
  const rateLimited = statusCode === 429

  const copyId = async () => {
    try { await navigator.clipboard.writeText(publicId || data?.public_id || '') ; setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* noop */ }
  }
  const share = async () => {
    const url = window.location.href
    try { await navigator.share({ title: 'CrowdResolve complaint', url }) } catch { await navigator.clipboard.writeText(url) }
  }

  /* save token for citizen convenience */
  useEffect(() => {
    if (data?.public_id && token && citizen !== undefined) saveTrackingToken(data.public_id, token)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.public_id])

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
      <h1 className="font-display text-2xl font-bold text-[var(--text)]">{t('track.title')}</h1>
      <div className="mt-4"><TrackIdSearch large /></div>

      {!parsed.ok && (
        <Card className="mt-6"><EmptyState title={t('errors.notFound')} body={t('track.invalidId')} /></Card>
      )}

      {parsed.ok && !token && (
        <Card className="mt-6">
          <CardHeader title={publicId || 'Complaint'} subtitle={t('track.secretPrompt')} />
          <form onSubmit={(e) => { e.preventDefault(); setSecret(secret.trim()) }} className="flex gap-2">
            <input value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={t('track.secretPlaceholder')}
              className="h-10 flex-1 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 text-sm outline-none focus:border-brand-500" />
            <Button type="submit">{t('track.loadSecret')}</Button>
          </form>
        </Card>
      )}

      {token && isLoading && (
        <Card className="mt-6 space-y-4">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-40 w-full" />
        </Card>
      )}

      {token && isError && (
        <Card className="mt-6">
          {rateLimited
            ? <EmptyState title={t('track.rateLimited')} />
            : <ErrorState title={t('track.notFound')} body={t('track.notFoundBody')} onRetry={() => void refetch()} />}
        </Card>
      )}

      {token && data && (
        <div className="mt-6 space-y-4">
          {/* header card */}
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-[var(--text-faint)]">{t('track.idLabel')}</p>
                <div className="mt-1 flex items-center gap-2">
                  <span className="font-display text-xl font-bold text-[var(--text)]">{data.public_id}</span>
                  <button onClick={() => void copyId()} className="rounded-lg p-1.5 text-[var(--text-muted)] hover:bg-[var(--surface-2)]" aria-label={t('track.copy')}>
                    {copied ? <Check className="h-4 w-4 text-brand-600" /> : <Copy className="h-4 w-4" />}
                  </button>
                </div>
              </div>
              <StatusChip status={data.status} />
            </div>

            {/* stepper */}
            <ol className="mt-6 flex items-center" aria-label={t('track.status')}>
              {TIMELINE.map((step, i) => {
                const idx = timelineIndex(data.status)
                const done = i < idx || (i === idx && ['resolved', 'closed'].includes(data.status))
                const active = i === idx && !['resolved', 'closed'].includes(data.status)
                const labels = t('track.timeline', { returnObjects: true }) as string[]
                return (
                  <li key={step} className="flex flex-1 flex-col items-center">
                    <div className="flex w-full items-center">
                      <div className={cn('h-0.5 flex-1', i === 0 ? 'bg-transparent' : done || active ? 'bg-brand-500' : 'bg-[var(--border)]')} />
                      <span className={cn('flex h-8 w-8 items-center justify-center rounded-full border-2 text-xs font-bold',
                        done ? 'border-brand-500 bg-brand-500 text-white' : active ? 'border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-900/40' : 'border-[var(--border)] bg-[var(--surface)] text-[var(--text-faint)]')}>
                        {done ? <Check className="h-4 w-4" /> : i + 1}
                      </span>
                      <div className={cn('h-0.5 flex-1', i === TIMELINE.length - 1 ? 'bg-transparent' : done ? 'bg-brand-500' : 'bg-[var(--border)]')} />
                    </div>
                    <span className={cn('mt-2 text-center text-[10px] font-medium leading-tight sm:text-xs',
                      done || active ? 'text-[var(--text)]' : 'text-[var(--text-faint)]')}>{labels[i]}</span>
                  </li>
                )
              })}
            </ol>
          </Card>

          {/* details */}
          <Card>
            <CardHeader title={t('track.status')} />
            <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
              <Detail icon={<Tag className="h-4 w-4" />} label={t('track.category')}>
                <span className="flex items-center gap-2">{data.category_label} <SeverityBadge severity={data.severity} score={data.priority_score} /></span>
              </Detail>
              <Detail icon={<Building2 className="h-4 w-4" />} label={t('track.department')}>{data.department || '—'}</Detail>
              <Detail icon={<Calendar className="h-4 w-4" />} label={t('track.filed')}>{formatDate(data.created_at)}</Detail>
              <Detail icon={<RefreshCw className="h-4 w-4" />} label={t('track.updated')}>{formatDateTime(data.updated_at || data.created_at)}</Detail>
              <Detail icon={<Calendar className="h-4 w-4" />} label={t('track.expected')}>{data.sla_deadline ? formatDate(data.sla_deadline) : '—'}</Detail>
              <Detail icon={<MapPin className="h-4 w-4" />} label={t('track.location')}>
                {data.location?.landmark || (data.location?.lat != null ? `${data.location.lat.toFixed(4)}, ${data.location.lon?.toFixed(4)}` : '—')}
                {data.incident?.citizens_affected ? <span className="ml-2 text-xs text-[var(--text-faint)]">· {data.incident.citizens_affected} {t('track.status').toLowerCase()}</span> : null}
              </Detail>
            </dl>
            {data.review_reason && (
              <p className="mt-4 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">{data.review_reason}</p>
            )}
          </Card>

          {/* resolution */}
          {(data.resolution_evidence?.length || data.resolved_at) && (
            <Card>
              <CardHeader title={t('track.proofPhoto')} />
              {data.resolution_evidence?.[0] && (
                <a href={`/api/media/${data.id}/${data.resolution_evidence[0].id}`} target="_blank" rel="noreferrer">
                  <img src={`/api/media/${data.id}/${data.resolution_evidence[0].id}`} alt={t('track.proofPhoto')}
                    className="max-h-64 rounded-xl border border-[var(--border)] object-cover" loading="lazy" />
                </a>
              )}
            </Card>
          )}

          {/* actions */}
          <Card className="flex flex-wrap items-center gap-3">
            {citizen && (
              <Button variant={notified ? 'secondary' : 'outline'} size="sm" onClick={() => setNotified(true)}>
                <Bell className="h-4 w-4" /> {notified ? '✓' : t('track.notifyMe')}
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => void share()}><Share2 className="h-4 w-4" /> {t('track.share')}</Button>
            <Button variant="outline" size="sm" onClick={() => window.print()}><Download className="h-4 w-4" /> {t('track.download')}</Button>
            {data.can_verify && (
              <Button size="sm" onClick={async () => {
                if (!token) return
                try { await complaintsApi.verify(data.public_id, token, 'confirm'); await refetch() } catch { /* surfaced via query */ }
              }}>{t('status.awaiting_verification')}</Button>
            )}
            <span className="ml-auto text-xs text-[var(--text-faint)]">Updated {formatDateTime(data.updated_at)}</span>
          </Card>
        </div>
      )}
    </div>
  )
}

function Detail({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2.5">
      <span className="mt-0.5 text-brand-600">{icon}</span>
      <div>
        <dt className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-faint)]">{label}</dt>
        <dd className="text-sm text-[var(--text)]">{children}</dd>
      </div>
    </div>
  )
}
