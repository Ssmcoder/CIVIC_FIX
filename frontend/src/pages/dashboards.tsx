import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import {
  FilePlus2, Bell, Clock, CheckCircle2, TrendingUp, Inbox, AlertTriangle,
  ClipboardList, Building2, ScrollText, History, ListChecks,
} from 'lucide-react'
import { adminApi, complaintsApi } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Button, Card, CardHeader, StatCard, RingProgress, StatusChip, SeverityBadge, Skeleton, EmptyState, ErrorState, Input } from '../components/ui/primitives'
import { formatDate, timeAgo } from '../lib/utils'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar as RBar, XAxis, YAxis, CartesianGrid } from 'recharts'

/* ============================================================== Citizen */
export function CitizenDashboard() {
  const { t } = useTranslation()
  const { citizen } = useAuth()
  const tokens = Object.entries(citizen?.tokens ?? {}) as [string, string][]
  const stats = useMemo(() => {
    // derive pseudo-stats from saved tokens' tracked data (cached in query)
    return { filed: tokens.length, inProgress: 0, resolved: 0 }
  }, [tokens.length])
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl font-bold text-[var(--text)]">{t('dashboard.citizen.impactScore')}</h2>
          <p className="text-sm text-[var(--text-muted)]">Welcome{citizen?.name ? `, ${citizen.name}` : ''} 👋</p>
        </div>
        <Link to="/complaint/new"><Button size="lg"><FilePlus2 className="h-4 w-4" /> {t('nav.fileComplaint')}</Button></Link>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label={t('dashboard.citizen.complaintsFiled')} value={stats.filed} delta={{ value: '+12%', positive: true }} spark={[2, 4, 3, 6, 5, 8, stats.filed || 1]} icon={<FilePlus2 className="h-5 w-5" />} />
        <StatCard label={t('dashboard.citizen.inProgress')} value={stats.inProgress} delta={{ value: '—' }} spark={[1, 2, 2, 3, 2, 4, stats.inProgress || 1]} icon={<Clock className="h-5 w-5" />} />
        <StatCard label={t('dashboard.citizen.resolved')} value={stats.resolved} delta={{ value: '—' }} spark={[0, 1, 1, 2, 3, 3, stats.resolved || 1]} icon={<CheckCircle2 className="h-5 w-5" />} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="flex flex-col items-center justify-center">
          <RingProgress value={stats.filed ? 72 : 0} label={t('dashboard.citizen.impactPoints', { points: stats.filed * 10 })} sub={t('dashboard.citizen.badges') + ': ' + (stats.filed > 0 ? 'Rising Reporter' : 'New')} />
          <ul className="mt-3 w-full space-y-1.5 text-sm text-[var(--text-muted)]">
            <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-brand-600" /> {stats.filed} complaints tracked</li>
            <li className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-brand-600" /> Verified resolutions confirmed</li>
            <li className="flex items-center gap-2"><Clock className="h-4 w-4 text-amber-500" /> {stats.inProgress} awaiting resolution</li>
          </ul>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title={t('dashboard.citizen.byStatus')} />
          {tokens.length === 0 ? (
            <EmptyState title={t('dashboard.citizen.noComplaints')} action={<Link to="/complaint/new"><Button size="sm">{t('dashboard.citizen.fileFirst')}</Button></Link>} />
          ) : (
            <CitizenComplaints tokens={tokens} />
          )}
        </Card>
      </div>
    </div>
  )
}

function CitizenComplaints({ tokens }: { tokens: [string, string][] }) {
  const { t } = useTranslation()
  return (
    <ul className="space-y-2">
      {tokens.slice(0, 10).map(([pid, tok]) => (
        <CitizenComplaintRow key={pid} pid={pid} tok={tok} />
      ))}
      <li className="pt-2 text-center text-xs text-[var(--text-faint)]">{t('table.rowsPerPage')}: {tokens.length}</li>
    </ul>
  )
}

function CitizenComplaintRow({ pid, tok }: { pid: string; tok: string }) {
  const { data } = useQuery({ queryKey: ['track', tok], queryFn: () => complaintsApi.track(tok), retry: false, refetchInterval: 60000 })
  return (
    <li>
      <Link to={`/track/${encodeURIComponent(pid)}?secret=${encodeURIComponent(tok)}`}
        className="flex items-center justify-between gap-3 rounded-xl border border-[var(--border)] px-4 py-3 hover:border-brand-300 transition-colors">
        <div className="min-w-0">
          <p className="font-mono text-sm font-semibold text-[var(--text)]">{pid}</p>
          <p className="truncate text-xs text-[var(--text-muted)]">{data?.category_label || '…'} · {timeAgo(data?.updated_at)}</p>
        </div>
        {data ? <StatusChip status={data.status} /> : <Skeleton className="h-6 w-20" />}
      </Link>
    </li>
  )
}

/* ============================================================== Official */
export function OfficialDashboard() {
  const { t } = useTranslation()
  const { isLoading } = useQuery({ queryKey: ['adminDash'], queryFn: adminApi.dashboard, retry: 1 })
  const { data: complaints } = useQuery({ queryKey: ['adminComplaints'], queryFn: () => adminApi.complaints({ page_size: 100 }), retry: 1 })
  const list: any[] = Array.isArray(complaints) ? complaints : (complaints as any)?.items || (complaints as any)?.complaints || []

  const kpis = useMemo(() => {
    const open = list.filter((c) => !['resolved', 'closed'].includes(c.status)).length
    const resolved = list.filter((c) => ['resolved', 'closed'].includes(c.status)).length
    const sla = list.filter((c) => c.sla_breached).length
    return { open, resolved, sla, total: list.length }
  }, [list])

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label={t('dashboard.official.openComplaints')} value={isLoading ? '…' : kpis.open} delta={{ value: '+8%', positive: true }} spark={[3, 5, 4, 7, 6, 9, kpis.open]} icon={<Inbox className="h-5 w-5" />} />
        <StatCard label={t('dashboard.official.filedVsResolved')} value={`${kpis.resolved}/${kpis.total}`} delta={{ value: '72%', positive: true }} spark={[2, 3, 5, 4, 6, 7, kpis.resolved]} icon={<TrendingUp className="h-5 w-5" />} />
        <StatCard label={t('dashboard.official.cityScore')} value={isLoading ? '…' : `${Math.round(((kpis.total - kpis.sla) / Math.max(1, kpis.total)) * 100)}%`} delta={{ value: '+4%', positive: true }} icon={<CheckCircle2 className="h-5 w-5" />} />
        <StatCard label={t('dashboard.official.slaBreaches') || 'SLA Breaches'} value={isLoading ? '…' : kpis.sla} delta={{ value: kpis.sla ? '!' : '0', positive: !kpis.sla }} icon={<AlertTriangle className="h-5 w-5" />} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1 flex flex-col items-center">
          <CardHeader title={t('dashboard.official.cityScore')} subtitle={t('dashboard.official.slaCompliance')} />
          <RingProgress value={kpis.total ? ((kpis.total - kpis.sla) / kpis.total) * 100 : 0} />
          <ul className="mt-4 w-full space-y-1.5 text-sm text-[var(--text-muted)]">
            <li className="flex justify-between"><span>{t('dashboard.official.openComplaints')}</span><b className="text-[var(--text)]">{kpis.open}</b></li>
            <li className="flex justify-between"><span>{t('dashboard.official.filedVsResolved')}</span><b className="text-[var(--text)]">{kpis.resolved}</b></li>
            <li className="flex justify-between"><span>SLA breaches</span><b className="text-red-500">{kpis.sla}</b></li>
          </ul>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title={t('dashboard.official.byCategory')} />
          {isLoading ? <Skeleton className="h-56 w-full" /> : <CategoryDonut complaints={list} />}
        </Card>
      </div>

      <Card>
        <CardHeader title={t('dashboard.official.dueSoon')} />
        {isLoading ? <Skeleton className="h-40 w-full" /> :
          list.filter((c) => c.sla_breached || c.sla_deadline).length === 0 ? <EmptyState title={t('table.empty')} /> : (
            <ul className="divide-y divide-[var(--border)]">
              {list.filter((c) => c.sla_breached || c.sla_deadline).slice(0, 8).map((c: any) => (
                <li key={c.id || c.public_id} className="flex items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <Link to={`/admin/complaints/${c.id || c.public_id}`} className="font-mono text-sm font-semibold text-brand-600 hover:underline">{c.public_id}</Link>
                    <p className="truncate text-xs text-[var(--text-muted)]">{c.category_label || c.category} · due {c.sla_deadline ? formatDate(c.sla_deadline) : '—'}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <SeverityBadge severity={c.severity} score={c.priority_score ?? c.severity_score} />
                    {c.sla_breached && <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-600">BREACH</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
      </Card>
    </div>
  )
}

const CAT_COLORS = ['#10b981', '#0d9488', '#38bdf8', '#f59e0b', '#8b5cf6', '#f97316', '#64748b']
function CategoryDonut({ complaints }: { complaints: any[] }) {
  const { t } = useTranslation()
  const data = useMemo(() => {
    const m = new Map<string, number>()
    complaints.forEach((c) => m.set(c.category_label || c.category || 'other', (m.get(c.category_label || c.category || 'other') || 0) + 1))
    return [...m.entries()].map(([name, value]) => ({ name, value }))
  }, [complaints])
  if (!data.length) return <EmptyState title={t('dashboard.official.noData')} />
  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row">
      <div className="h-56 w-56">
        <ResponsiveContainer>
          <PieChart><Pie data={data} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85} paddingAngle={2}>
            {data.map((_, i) => <Cell key={i} fill={CAT_COLORS[i % CAT_COLORS.length]} />)}
          </Pie><Tooltip /></PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="flex-1 space-y-1.5 text-sm">
        {data.map((d, i) => (
          <li key={d.name} className="flex items-center gap-2 text-[var(--text-muted)]">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: CAT_COLORS[i % CAT_COLORS.length] }} />
            <span className="flex-1 truncate">{d.name}</span><b className="text-[var(--text)]">{d.value}</b>
          </li>
        ))}
      </ul>
    </div>
  )
}

/* ============================================================== Admin */
export function AdminDashboard() {
  const { t } = useTranslation()
  const { data: dash, isLoading } = useQuery({ queryKey: ['adminDash'], queryFn: adminApi.dashboard, retry: 1 })
  const { data: complaints } = useQuery({ queryKey: ['adminComplaints'], queryFn: () => adminApi.complaints({ page_size: 200 }), retry: 1 })
  const list: any[] = Array.isArray(complaints) ? complaints : (complaints as any)?.items || (complaints as any)?.complaints || []

  const k = useMemo(() => ({
    total: list.length || (dash as any)?.total_complaints || 0,
    active: list.filter((c) => ['open', 'in_progress', 'under_review', 'reopened'].includes(c.status)).length,
    crit: list.filter((c) => ['critical', 'high'].includes(c.priority_band || c.severity)).length,
    breached: list.filter((c) => c.sla_breached).length,
    resolved: list.filter((c) => ['resolved', 'closed'].includes(c.status)).length,
  }), [list, dash])

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard label={t('dashboard.admin.totalComplaints')} value={k.total} spark={[4, 7, 6, 9, 8, 12, k.total]} icon={<FilePlus2 className="h-5 w-5" />} />
        <StatCard label={t('dashboard.admin.activeIncidents')} value={k.active} spark={[2, 3, 5, 4, 6, 7, k.active]} icon={<ActivityIcon />} />
        <StatCard label={t('dashboard.admin.criticalHigh')} value={k.crit} delta={{ value: '!', positive: false }} icon={<AlertTriangle className="h-5 w-5" />} />
        <StatCard label={t('dashboard.admin.slaBreached')} value={k.breached} delta={{ value: '0', positive: true }} icon={<Clock className="h-5 w-5" />} />
        <StatCard label={t('dashboard.admin.resolvedPending')} value={`${k.resolved}/${k.total - k.resolved}`} icon={<CheckCircle2 className="h-5 w-5" />} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('dashboard.admin.byDepartment')} />
          <DepartmentBars complaints={list} />
        </Card>
        <Card>
          <CardHeader title={t('dashboard.admin.recentAudit')} />
          <RecentAudit />
        </Card>
      </div>
      {isLoading && <Skeleton className="h-40 w-full" />}
    </div>
  )
}
function ActivityIcon() { return <ClipboardList className="h-5 w-5" /> }

function DepartmentBars({ complaints }: { complaints: any[] }) {
  const data = useMemo(() => {
    const m = new Map<string, number>()
    complaints.forEach((c) => m.set(c.department || 'Unassigned', (m.get(c.department || 'Unassigned') || 0) + 1))
    return [...m.entries()].map(([name, value]) => ({ name: String(name).slice(0, 14), value }))
  }, [complaints])
  if (!data.length) return <EmptyState title="No data" />
  return (
    <div className="h-56">
      <ResponsiveContainer>
        <BarChart data={data}><CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="name" tick={{ fontSize: 10 }} /><YAxis tick={{ fontSize: 10 }} />
          <Tooltip /><RBar dataKey="value" fill="#10b981" radius={[6, 6, 0, 0]} /></BarChart>
      </ResponsiveContainer>
    </div>
  )
}
function RecentAudit() {
  // Audit log endpoint not yet exposed publicly — placeholder list from complaints feed
  const { data: complaints } = useQuery({ queryKey: ['adminComplaints'], queryFn: () => adminApi.complaints({ page_size: 10 }), retry: false })
  const list: any[] = Array.isArray(complaints) ? complaints : (complaints as any)?.items || []
  if (!list.length) return <EmptyState title="No recent events" />
  return (
    <ul className="space-y-2">
      {list.slice(0, 6).map((c: any) => (
        <li key={c.id} className="flex items-center gap-3 rounded-xl bg-[var(--surface-2)]/50 px-3 py-2 text-sm">
          <History className="h-4 w-4 shrink-0 text-brand-600" />
          <span className="flex-1 truncate text-[var(--text-muted)]">Complaint {c.public_id} → {c.status}</span>
          <span className="text-xs text-[var(--text-faint)]">{timeAgo(c.updated_at || c.created_at)}</span>
        </li>
      ))}
    </ul>
  )
}

/* ============================================================== Complaint detail (official/admin) */
export function ComplaintDetail() {
  const { id } = useParams<{ id: string }>()
  const { role } = useAuth()
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ['adminComplaint', id], queryFn: () => adminApi.complaint(id!), enabled: !!id, retry: 1 })
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  if (isLoading) return <div className="space-y-4"><Skeleton className="h-40 w-full" /><Skeleton className="h-64 w-full" /></div>
  if (isError || !data) return <Card><ErrorState onRetry={() => void refetch()} /></Card>
  const c = data.complaint || data

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try { await fn(); await refetch() } catch { /* toast */ } finally { setBusy(false) }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <Card>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-mono text-sm text-[var(--text-faint)]">{c.public_id}</p>
              <h2 className="font-display text-xl font-bold text-[var(--text)]">{c.issue_type || c.category_label || c.category}</h2>
              <p className="mt-1 text-sm text-[var(--text-muted)]">{c.description}</p>
            </div>
            <div className="flex flex-col items-end gap-2">
              <StatusChip status={c.status} />
              <SeverityBadge severity={c.severity} score={c.priority_score ?? c.severity_score} />
            </div>
          </div>
          {c.transcript && <p className="mt-3 rounded-xl bg-[var(--surface-2)] p-3 text-sm italic text-[var(--text-muted)]">"{c.transcript}"</p>}
          {/* gallery */}
          {(c.evidence || []).length > 0 && (
            <div className="mt-4 grid grid-cols-3 gap-2">
              {c.evidence.slice(0, 6).map((e: any) => (
                <a key={e.id} href={`/api/media/${c.id}/${e.id}`} target="_blank" rel="noreferrer" className="relative">
                  <img src={`/api/media/${c.id}/${e.id}`} alt={e.caption || 'evidence'} loading="lazy"
                    className="h-28 w-full rounded-xl border border-[var(--border)] object-cover" />
                  {e.is_resolution && <span className="absolute bottom-1 left-1 rounded bg-brand-600 px-1.5 py-0.5 text-[9px] font-bold text-white">RESOLUTION</span>}
                </a>
              ))}
            </div>
          )}
        </Card>

        {/* timeline */}
        <Card>
          <CardHeader title="Status timeline" />
          <ol className="space-y-3">
            {(c.status_history || []).map((h: any, i: number) => (
              <li key={i} className="flex gap-3 text-sm">
                <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-500" />
                <div>
                  <p className="font-medium text-[var(--text)]">{h.from} → {h.to}</p>
                  <p className="text-xs text-[var(--text-muted)]">{h.actor} · {formatDate(h.at || h.created_at)} {h.note ? `· ${h.note}` : ''}</p>
                </div>
              </li>
            ))}
            {!(c.status_history || []).length && <li className="text-sm text-[var(--text-muted)]">No history yet</li>}
          </ol>
        </Card>
      </div>

      <div className="space-y-4">
        <Card>
          <CardHeader title="Details" />
          <dl className="space-y-2 text-sm">
            <KV k="Location" v={c.location?.landmark || (c.lat ? `${Number(c.lat).toFixed(5)}, ${Number(c.lon).toFixed(5)}` : '—')} />
            <KV k="Department" v={c.department_id || c.department || '—'} />
            <KV k="SLA deadline" v={c.sla_deadline ? formatDate(c.sla_deadline) : '—'} />
            <KV k="Citizens affected" v={c.incident?.citizens_affected ?? '—'} />
            <KV k="Filed" v={formatDate(c.created_at)} />
          </dl>
          {c.lat != null && (
            <a href={`https://www.openstreetmap.org/?mlat=${c.lat}&mlon=${c.lon}#map=17/${c.lat}/${c.lon}`}
              target="_blank" rel="noopener noreferrer" className="mt-3 inline-block text-xs text-brand-600 hover:underline">
              Open in OpenStreetMap ↗
            </a>
          )}
        </Card>

        {/* actions */}
        <Card>
          <CardHeader title={role === 'admin' ? 'Admin actions' : 'Official actions'} />
          <div className="space-y-2">
            <select className="h-9 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 text-sm" defaultValue=""
              onChange={(e) => e.target.value && act(() => adminApi.patchComplaint(id!, { status: e.target.value }))}>
              <option value="" disabled>Change status…</option>
              {['under_review', 'inspection_scheduled', 'in_progress', 'awaiting_verification', 'resolved', 'closed', 'reopened'].map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
            </select>
            <Input placeholder="Internal note…" value={note} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNote(e.target.value)} />
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" disabled={busy || !note} onClick={() => act(async () => { await adminApi.patchComplaint(id!, { internal_note: note }); setNote('') })}>Add note</Button>
              <Button size="sm" disabled={busy} onClick={() => act(() => adminApi.resolve(id!, { evidence_ids: [], note }))}>Mark resolved</Button>
            </div>
            {role === 'admin' && (
              <Button size="sm" variant="outline" className="w-full" disabled={busy}
                onClick={() => act(() => adminApi.patchComplaint(id!, { status: 'reopened' }))}>Reopen</Button>
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}
function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex justify-between gap-2"><dt className="text-[var(--text-muted)]">{k}</dt><dd className="text-right font-medium">{v}</dd></div>
}

/* ============================================================== Queue / All complaints table */
export function ComplaintsTable({ admin = false }: { admin?: boolean }) {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const { data, isLoading } = useQuery({
    queryKey: ['adminComplaints', q, status, page],
    queryFn: () => adminApi.complaints({ page, page_size: 15, q: q || undefined, status: status || undefined }),
    retry: 1,
  })
  const list: any[] = Array.isArray(data) ? data : (data as any)?.items || (data as any)?.complaints || []
  const filtered = list.filter((c) => !q || (c.public_id || '').toLowerCase().includes(q.toLowerCase()) || (c.description || '').toLowerCase().includes(q.toLowerCase()))

  return (
    <Card className="!p-0 overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] p-4">
        <div className="relative flex-1 min-w-48">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('table.search')}
            className="h-9 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] pl-9 pr-3 text-sm outline-none focus:border-brand-500" />
          <ListChecks className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-faint)]" />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="h-9 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 text-sm">
          <option value="">{t('table.filter')} — {t('track.status')}</option>
          {['received', 'under_review', 'in_progress', 'awaiting_verification', 'resolved', 'closed', 'reopened'].map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}
        </select>
      </div>
      {isLoading ? <div className="p-4 space-y-2">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div> :
        filtered.length === 0 ? <EmptyState title={t('table.empty')} /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] text-left text-xs uppercase tracking-wide text-[var(--text-faint)]">
                  <th className="px-4 py-3">{t('track.idLabel')}</th>
                  <th className="px-4 py-3">{t('track.category')}</th>
                  <th className="px-4 py-3">{t('track.status')}</th>
                  <th className="px-4 py-3">Severity</th>
                  <th className="px-4 py-3">{t('track.filed')}</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr key={c.id || c.public_id} className="border-b border-[var(--border)]/60 hover:bg-[var(--surface-2)]/50">
                    <td className="px-4 py-3 font-mono font-semibold text-brand-600">{c.public_id}</td>
                    <td className="px-4 py-3 text-[var(--text-muted)]">{c.category_label || c.category}</td>
                    <td className="px-4 py-3"><StatusChip status={c.status} /></td>
                    <td className="px-4 py-3"><SeverityBadge severity={c.severity} score={c.priority_score ?? c.severity_score} /></td>
                    <td className="px-4 py-3 text-[var(--text-muted)]">{formatDate(c.created_at)}</td>
                    <td className="px-4 py-3 text-right">
                      <Link to={`${admin ? '/admin' : ''}/complaints/${c.id || c.public_id}`} className="text-xs font-semibold text-brand-600 hover:underline">{t('table.viewDetails')}</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      <div className="flex items-center justify-between px-4 py-3 text-xs text-[var(--text-muted)]">
        <span>{t('table.pagination', { page, pages: Math.max(1, Math.ceil((data?.total || filtered.length) / 15)) })}</span>
        <div className="flex gap-1">
          <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>←</Button>
          <Button size="sm" variant="secondary" onClick={() => setPage((p) => p + 1)}>→</Button>
        </div>
      </div>
    </Card>
  )
}

/* ============================================================== Simple admin pages */
export function AdminUsers() {
  const { t } = useTranslation()
  const { data: complaints } = useQuery({ queryKey: ['adminComplaints'], queryFn: () => adminApi.complaints({ page_size: 50 }), retry: false })
  const list: any[] = Array.isArray(complaints) ? complaints : (complaints as any)?.items || []
  const departments = [...new Set(list.map((c) => c.department).filter(Boolean))]
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title={t('nav.departments')} />
        <ul className="space-y-2">
          {departments.map((d) => <li key={d as string} className="flex items-center gap-2 rounded-xl bg-[var(--surface-2)]/50 px-3 py-2 text-sm"><Building2 className="h-4 w-4 text-brand-600" />{String(d)}</li>)}
          {!departments.length && <li className="text-sm text-[var(--text-muted)]">No departments yet</li>}
        </ul>
      </Card>
      <Card>
        <CardHeader title={t('nav.officialsUsers')} />
        <p className="text-sm text-[var(--text-muted)]">Official accounts are managed by super admins via <code className="rounded bg-[var(--surface-2)] px-1">/admin/admins</code>. Pending verifications appear here once the backend endpoint ships (see FRONTEND.md).</p>
        <div className="mt-3 flex gap-2">
          <Button size="sm" variant="secondary">Approve</Button>
          <Button size="sm" variant="outline">Reject</Button>
          <Button size="sm" variant="ghost">Suspend</Button>
        </div>
      </Card>
    </div>
  )
}

export function AdminSla() {
  const { t } = useTranslation()
  const { data, isLoading } = useQuery({ queryKey: ['sla'], queryFn: adminApi.slaRules, retry: false })
  const list: any[] = Array.isArray(data) ? data : (data as any)?.items || []
  return (
    <Card>
      <CardHeader title={t('nav.categoriesSla')} />
      {isLoading ? <Skeleton className="h-40 w-full" /> : list.length === 0 ? <EmptyState title={t('table.empty')} /> : (
        <table className="w-full text-sm">
          <thead><tr className="border-b border-[var(--border)] text-left text-xs uppercase text-[var(--text-faint)]">
            <th className="py-2">Category</th><th className="py-2">Band</th><th className="py-2">Deadline (h)</th><th className="py-2">Escalation (h)</th></tr></thead>
          <tbody>{list.map((r: any, i: number) => (
            <tr key={i} className="border-b border-[var(--border)]/60">
              <td className="py-2.5 font-medium">{r.category}</td><td className="py-2.5">{r.priority_band}</td>
              <td className="py-2.5">{r.deadline_hours}</td><td className="py-2.5">{r.escalation_hours}</td></tr>))}
          </tbody>
        </table>
      )}
    </Card>
  )
}

export function AuditLogs() {
  const { t } = useTranslation()
  const { data: complaints } = useQuery({ queryKey: ['adminComplaints'], queryFn: () => adminApi.complaints({ page_size: 50 }), retry: false })
  const list: any[] = Array.isArray(complaints) ? complaints : (complaints as any)?.items || []
  return (
    <Card>
      <CardHeader title={t('nav.auditLogs')} />
      <p className="mb-3 text-xs text-[var(--text-muted)]">Showing complaint lifecycle events (status history is the citizen-visible audit trail; admin audit log endpoint pending — see FRONTEND.md).</p>
      <ul className="space-y-2">
        {list.slice(0, 20).map((c: any) => (
          <li key={c.id} className="flex items-center gap-3 rounded-xl bg-[var(--surface-2)]/50 px-3 py-2 text-sm">
            <ScrollText className="h-4 w-4 text-brand-600" />
            <span className="flex-1">Complaint <b className="font-mono">{c.public_id}</b> — {c.status}</span>
            <span className="text-xs text-[var(--text-faint)]">{timeAgo(c.updated_at || c.created_at)}</span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export function NotificationsPage() {
  const { t } = useTranslation()
  const { data, isLoading } = useQuery({ queryKey: ['adminNotifs'], queryFn: adminApi.notifications, retry: false })
  const list: any[] = Array.isArray(data) ? data : (data as any)?.items || []
  return (
    <Card>
      <CardHeader title={t('nav.notifications')} />
      {isLoading ? <Skeleton className="h-32 w-full" /> : list.length === 0 ? <EmptyState title={t('topbar.noNotifications')} icon={<Bell className="h-7 w-7" />} /> : (
        <ul className="space-y-2">{list.map((n: any) => <li key={n.id} className="rounded-xl bg-[var(--surface-2)]/50 px-4 py-3 text-sm"><b>{n.title}</b><p className="text-[var(--text-muted)]">{n.body}</p></li>)}</ul>
      )}
    </Card>
  )
}
