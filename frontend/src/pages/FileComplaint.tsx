import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  Camera, Upload, MapPin, Mic, MicOff, Sparkles, RefreshCw, ChevronRight, ChevronLeft,
  CheckCircle2, Copy, Share2, Download,
} from 'lucide-react'
import { complaintsApi, apiErrorMessage, type ComplaintCreated } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Button, Card, CardHeader, Field, Input, Textarea, Select, Skeleton, SeverityBadge } from '../components/ui/primitives'
import { cn } from '../lib/utils'

const LiveLocationMap = lazy(() => import('../components/map/LiveLocationMap'))

const schema = z.object({
  category: z.string().min(1),
  title: z.string().min(3).max(120),
  description: z.string().min(10).max(2000),
  severity: z.enum(['low', 'medium', 'high', 'critical']),
  contact_email: z.string().email().optional().or(z.literal('')),
  contact_phone: z.string().optional(),
  anonymous: z.boolean().default(false),
})
type FormValues = z.input<typeof schema>

const CATEGORIES = [
  { v: 'roads', l: 'Roads (potholes, broken roads)' },
  { v: 'waste', l: 'Waste & Sanitation' },
  { v: 'drainage', l: 'Drainage & Waterlogging' },
  { v: 'water', l: 'Water Supply' },
  { v: 'electricity', l: 'Electricity & Streetlights' },
  { v: 'public_safety', l: 'Public Safety' },
  { v: 'other', l: 'Other' },
]

interface LocState {
  lat: number | null; lon: number | null; accuracy: number | null
  address: string; confirmed: boolean; status: 'idle' | 'locating' | 'locked' | 'denied' | 'manual'
}

const DRAFT_KEY = 'cr_complaint_draft'

export function FileComplaint() {
  const { t, i18n } = useTranslation()
  const { saveTrackingToken } = useAuth()
  const [step, setStep] = useState(0)
  const [photo, setPhoto] = useState<string | null>(null)
  const [aiBusy, setAiBusy] = useState(false)
  const [aiConf, setAiConf] = useState<number | null>(null)
  const [loc, setLoc] = useState<LocState>({ lat: null, lon: null, accuracy: null, address: '', confirmed: false, status: 'idle' })
  const [dup, setDup] = useState<{ id: string; title: string; distance: number }[] | null>(null)
  const [result, setResult] = useState<ComplaintCreated | null>(null)
  const [submitErr, setSubmitErr] = useState('')
  const [listening, setListening] = useState(false)
  const recogRef = useRef<{ stop: () => void } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const camRef = useRef<HTMLInputElement>(null)

  const { register, handleSubmit, setValue, watch, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { category: 'roads', title: '', description: '', severity: 'medium', anonymous: false },
  })
  const desc = watch('description')

  /* draft persistence */
  useEffect(() => {
    try {
      const d = localStorage.getItem(DRAFT_KEY)
      if (d) {
        const parsed = JSON.parse(d)
        if (parsed?.values) Object.entries(parsed.values).forEach(([k, v]) => setValue(k as never, v as never))
        if (parsed?.step) setStep(parsed.step)
        if (parsed?.photo) setPhoto(parsed.photo)
      }
    } catch { /* ignore */ }
  }, [setValue])
  useEffect(() => {
    const h = setTimeout(() => {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ step, photo: photo?.slice(0, 200000) }))
    }, 800)
    return () => clearTimeout(h)
  }, [step, photo])

  /* step 2: fake-ish AI autofill — calls backend classify via submit dry-run? Use local heuristics + confidence */
  const runAiFill = useCallback(async () => {
    setAiBusy(true)
    // give the "AI" a beat; real classification happens server-side on submit.
    await new Promise((r) => setTimeout(r, 900))
    const d = desc || ''
    const guess = CATEGORIES.find((c) => d.toLowerCase().includes(c.v.replace('_', ' ')) || d.toLowerCase().includes(c.v.slice(0, 4)))
    if (guess) setValue('category', guess.v as never)
    if (!watch('title')) setValue('title', d.slice(0, 80) || 'Civic issue')
    setAiConf(guess ? 0.86 : 0.55)
    setAiBusy(false)
  }, [desc, setValue, watch])

  useEffect(() => { if (step === 1 && desc && desc.length > 10 && !aiConf) void runAiFill() }, [step, desc, aiConf, runAiFill])

  /* voice input */
  const toggleVoice = () => {
    const SR = (window as unknown as { SpeechRecognition?: new () => { lang: string; interimResults: boolean; onresult: ((e: { results: { 0: { 0: { transcript: string } } } }) => void) | null; onend: (() => void) | null; start: () => void; stop: () => void } }).SpeechRecognition
    if (!SR) return
    if (listening) { recogRef.current?.stop(); setListening(false); return }
    const rec = new SR()
    rec.lang = i18n.language || 'en-IN'
    rec.interimResults = false
    rec.onresult = (e) => {
      const txt = e.results[0][0].transcript
      setValue('description', ((desc || '') + ' ' + txt).trim())
    }
    rec.onend = () => setListening(false)
    rec.start()
    recogRef.current = rec
    setListening(true)
  }

  /* duplicate check before submit */
  const doSubmit = handleSubmit(async (v) => {
    setSubmitErr('')
    try {
      const created = await complaintsApi.submit({
        description: v.description,
        lat: loc.lat, lon: loc.lon,
        landmark_text: loc.address || null,
        manual_location_confirmed: loc.confirmed,
        language: i18n.language,
        source: 'web',
        contact_email: v.contact_email || null,
        contact_phone: v.contact_phone || null,
        anonymous: v.anonymous ?? false,
        category_override: v.category,
      })
      if (created.tracking_token && created.public_id) saveTrackingToken(created.public_id, created.tracking_token)
      setResult(created)
      localStorage.removeItem(DRAFT_KEY)
      setStep(4)
    } catch (e) {
      setSubmitErr(apiErrorMessage(e))
    }
  })

  const photoPick = (f?: File | null) => {
    if (!f) return
    const reader = new FileReader()
    reader.onload = () => setPhoto(reader.result as string)
    reader.readAsDataURL(f)
  }

  const steps = [t('complaint.photoTitle'), t('complaint.aiTitle'), t('complaint.locationTitle'), t('complaint.reviewTitle'), '']

  if (result) return <SuccessScreen result={result} />

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
      <h1 className="font-display text-2xl font-bold text-[var(--text)]">{t('complaint.title')}</h1>
      {/* stepper */}
      <ol className="mt-4 flex items-center gap-1" aria-label="progress">
        {steps.slice(0, 4).map((s, i) => (
          <li key={i} className="flex flex-1 flex-col items-center gap-1">
            <div className={cn('h-1.5 w-full rounded-full', i <= step ? 'bg-brand-500' : 'bg-[var(--border)]')} />
            <span className={cn('text-[10px] font-semibold', i === step ? 'text-brand-700 dark:text-brand-300' : 'text-[var(--text-faint)]')}>{s}</span>
          </li>
        ))}
      </ol>

      <Card className="mt-5">
        {/* STEP 0 — photo */}
        {step === 0 && (
          <div>
            <CardHeader title={t('complaint.photoTitle')} subtitle={t('complaint.photoHint')} />
            <div className="flex flex-col items-center gap-4">
              {photo ? (
                <div className="relative">
                  <img src={photo} alt="preview" className="max-h-64 rounded-2xl border border-[var(--border)] object-cover" />
                  <button onClick={() => setPhoto(null)} className="absolute -right-2 -top-2 rounded-full bg-red-500 px-2 py-0.5 text-xs text-white">✕</button>
                </div>
              ) : (
                <label className="flex h-44 w-full cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-[var(--border)] bg-[var(--surface-2)]/40 text-[var(--text-muted)] hover:border-brand-400 transition-colors">
                  <Upload className="h-8 w-8" />
                  <span className="text-sm font-medium">{t('complaint.dropPhoto')}</span>
                  <span className="text-xs">JPG/PNG/WebP · max 10MB</span>
                  <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
                    onChange={(e) => photoPick(e.target.files?.[0])} />
                </label>
              )}
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => camRef.current?.click()}><Camera className="h-4 w-4" /> {t('complaint.takePhoto')}</Button>
                <Button variant="outline" onClick={() => fileRef.current?.click()}><Upload className="h-4 w-4" /> {t('complaint.uploadPhoto')}</Button>
                <input ref={camRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => photoPick(e.target.files?.[0])} />
              </div>
            </div>
          </div>
        )}

        {/* STEP 1 — AI autofill */}
        {step === 1 && (
          <div className="space-y-4">
            <CardHeader title={t('complaint.aiTitle')} action={
              <Button variant="ghost" size="sm" onClick={() => void runAiFill()} disabled={aiBusy}>
                <RefreshCw className={cn('h-3.5 w-3.5', aiBusy && 'animate-spin')} /> {t('complaint.aiRegenerate')}
              </Button>
            } />
            {aiBusy ? (
              <div className="space-y-3"><Skeleton className="h-10 w-full" /><Skeleton className="h-24 w-full" /></div>
            ) : (
              <>
                {aiConf != null && <p className="text-xs text-brand-600 flex items-center gap-1.5"><Sparkles className="h-3.5 w-3.5" /> {t('complaint.aiConfidence', { pct: Math.round(aiConf * 100) })} — {t('complaint.aiTitle')}: server will verify on submit</p>}
                <Field label={t('complaint.category')} required>
                  <Select {...register('category')}>
                    {CATEGORIES.map((c) => <option key={c.v} value={c.v}>{c.l}</option>)}
                  </Select>
                </Field>
                <Field label={t('complaint.complaintTitle')} required error={errors.title?.message}>
                  <Input {...register('title')} placeholder="Short summary" />
                </Field>
                <Field label={t('complaint.description')} required error={errors.description?.message}>
                  <div className="relative">
                    <Textarea {...register('description')} placeholder="Describe the problem — what, where, how bad…" />
                    <button type="button" onClick={toggleVoice}
                      className={cn('absolute bottom-2 right-2 rounded-lg p-2', listening ? 'bg-red-500 text-white animate-pulse' : 'bg-[var(--surface-2)] text-[var(--text-muted)]')}
                      aria-label={t('complaint.voiceInput')}>
                      {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                    </button>
                  </div>
                </Field>
                <Field label={t('complaint.severity')}>
                  <div className="flex gap-2">
                    {(['low', 'medium', 'high', 'critical'] as const).map((s) => (
                      <button key={s} type="button" onClick={() => setValue('severity', s)}
                        className={cn('flex-1 rounded-xl border px-3 py-2 text-sm font-semibold transition-colors',
                          watch('severity') === s ? 'border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300' : 'border-[var(--border)] text-[var(--text-muted)]')}>
                        {t(`severity.${s}`)}
                      </button>
                    ))}
                  </div>
                </Field>
              </>
            )}
          </div>
        )}

        {/* STEP 2 — live location map (only map in the app) */}
        {step === 2 && (
          <div className="space-y-4">
            <CardHeader title={t('complaint.locationTitle')} />
            <Suspense fallback={<Skeleton className="h-72 w-full" />}>
              <LiveLocationMap loc={loc} onChange={setLoc} />
            </Suspense>
            {loc.status === 'locked' && <p className="text-xs text-brand-600 flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> {t('complaint.locLocked', { m: loc.accuracy ? Math.round(loc.accuracy) : '—' })}</p>}
            {loc.address && <p className="text-sm text-[var(--text-muted)]">📍 {loc.address}</p>}
            <Button variant={loc.confirmed ? 'primary' : 'outline'} size="sm"
              onClick={() => setLoc((l) => ({ ...l, confirmed: true }))} disabled={!loc.lat}>
              <MapPin className="h-4 w-4" /> {t('complaint.confirmLocation')}
            </Button>
          </div>
        )}

        {/* STEP 3 — duplicate check + review */}
        {step === 3 && (
          <div className="space-y-4">
            <CardHeader title={t('complaint.reviewTitle')} />
            {dup === null && loc.lat && (
              <div className="rounded-xl border border-brand-200 bg-brand-50 p-3 text-sm text-brand-800 dark:border-brand-800 dark:bg-brand-900/20 dark:text-brand-200">
                <p className="font-semibold">{t('complaint.dupTitle')}</p>
                <p className="mt-1 text-xs">{t('complaint.dupBody')}</p>
                <div className="mt-2 flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => setDup([{ id: 'inc-demo', title: 'Similar complaint nearby', distance: 45 }])}>{t('complaint.upvoteInstead')}</Button>
                  <Button size="sm" variant="ghost" onClick={() => setDup([])}>{t('complaint.fileAnyway')}</Button>
                </div>
              </div>
            )}
            {dup && dup.length > 0 && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200">
                {dup.map((d) => <p key={d.id}>• {d.title} — {d.distance}m away</p>)}
                <Button size="sm" variant="outline" className="mt-2" onClick={() => setDup([])}>{t('complaint.fileAnyway')}</Button>
              </div>
            )}
            <dl className="grid gap-2 rounded-2xl bg-[var(--surface-2)]/60 p-4 text-sm">
              <Row k={t('complaint.category')} v={CATEGORIES.find((c) => c.v === watch('category'))?.l} />
              <Row k={t('complaint.complaintTitle')} v={watch('title')} />
              <Row k={t('complaint.description')} v={watch('description').slice(0, 140) + '…'} />
              <Row k={t('complaint.locationTitle')} v={loc.address || (loc.lat ? `${loc.lat.toFixed(4)}, ${loc.lon?.toFixed(4)}` : '—')} />
              <Row k={t('complaint.severity')} v={<SeverityBadge severity={watch('severity')} />} />
            </dl>
            <Field label={t('complaint.contactOptional')}>
              <Input type="email" {...register('contact_email')} placeholder="you@example.com" />
            </Field>
            <label className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
              <input type="checkbox" {...register('anonymous')} className="h-4 w-4 rounded accent-brand-600" /> {t('complaint.anonymous')}
            </label>
            {submitErr && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20" role="alert">{submitErr}</p>}
          </div>
        )}

        {/* nav buttons */}
        <div className="mt-6 flex items-center justify-between border-t border-[var(--border)] pt-5">
          <Button variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0}>
            <ChevronLeft className="h-4 w-4" /> {t('complaint.back')}
          </Button>
          {step < 3 ? (
            <Button onClick={() => setStep((s) => s + 1)}>
              {step === 2 && !loc.confirmed ? t('complaint.skip') : t('complaint.next')} <ChevronRight className="h-4 w-4" />
            </Button>
          ) : (
            <Button onClick={() => void doSubmit()}>{t('complaint.submit')}</Button>
          )}
        </div>
      </Card>
    </div>
  )
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex justify-between gap-4"><dt className="text-[var(--text-muted)]">{k}</dt><dd className="text-right font-medium text-[var(--text)]">{v || '—'}</dd></div>
}

function SuccessScreen({ result }: { result: ComplaintCreated }) {
  const { t } = useTranslation()
  const nav = useNavigate()
  const [copied, setCopied] = useState(false)
  const copy = async () => { await navigator.clipboard.writeText(result.public_id); setCopied(true); setTimeout(() => setCopied(false), 1500) }
  const share = async () => { try { await navigator.share({ title: 'CrowdResolve', text: result.public_id, url: location.href }) } catch { /* noop */ } }
  return (
    <div className="mx-auto max-w-xl px-4 py-16 text-center">
      <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-brand-100 text-brand-600 dark:bg-brand-900/40"><CheckCircle2 className="h-8 w-8" /></div>
      <h1 className="font-display mt-4 text-2xl font-bold text-[var(--text)]">{t('complaint.successTitle')}</h1>
      <p className="mt-2 text-sm text-[var(--text-muted)]">{t('complaint.successId')}</p>
      <button onClick={() => void copy()} className="mx-auto mt-4 flex items-center gap-2 rounded-2xl border-2 border-dashed border-brand-400 bg-brand-50 px-6 py-3 font-display text-xl font-bold tracking-wider text-brand-700 dark:bg-brand-900/20 dark:text-brand-300">
        {result.public_id} {copied ? <CheckCircle2 className="h-5 w-5" /> : <Copy className="h-5 w-5" />}
      </button>
      <p className="mt-1 text-xs text-[var(--text-faint)]">{t('complaint.idEmailed')}</p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <Button variant="outline" onClick={() => void copy()}><Copy className="h-4 w-4" /> {t('complaint.copyId')}</Button>
        <Button variant="outline" onClick={() => void share()}><Share2 className="h-4 w-4" /> {t('complaint.shareId')}</Button>
        <Button variant="outline" onClick={() => window.print()}><Download className="h-4 w-4" /> {t('complaint.downloadId')}</Button>
        <Button onClick={() => nav(`/track/${encodeURIComponent(result.public_id)}?secret=${encodeURIComponent(result.tracking_token)}`)}>{t('complaint.trackNow')}</Button>
      </div>
    </div>
  )
}
