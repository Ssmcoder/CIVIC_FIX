import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MessageCircle, X, Send } from 'lucide-react'
import { chatApi } from '../../lib/api'
import { cn } from '../../lib/utils'

/**
 * Floating assistant — wires to the backend chat session API.
 * Session token is kept in memory for the panel's lifetime.
 */
export function ChatWidget() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [sid, setSid] = useState<string | null>(null)
  const [stok, setStok] = useState<string | null>(null)
  const [msgs, setMsgs] = useState<{ role: string; content: string }[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, open])

  const ensureSession = async () => {
    if (sid && stok) return { sid, stok }
    const s = await chatApi.createSession()
    setSid(s.session_id); setStok(s.session_token)
    setMsgs([{ role: 'assistant', content: s.greeting || 'Hello! How can I help?' }])
    return { sid: s.session_id as string, stok: s.session_token as string }
  }

  const send = async () => {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    setMsgs((m) => [...m, { role: 'user', content: text }])
    setBusy(true)
    try {
      const s = await ensureSession()
      const r = await chatApi.send(s.sid, s.stok, text)
      setMsgs((m) => [...m, { role: 'assistant', content: r.reply || '…' }])
    } catch {
      setMsgs((m) => [...m, { role: 'assistant', content: 'Sorry — I could not reach the assistant right now. Please try again.' }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {open && (
        <div className="fixed bottom-24 right-4 z-50 flex h-[28rem] w-[22rem] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-pop)] sm:bottom-6 sm:right-6" role="dialog" aria-label={t('chat.title')}>
          <div className="flex items-center gap-2 bg-gradient-to-r from-brand-600 to-teal-brand-600 px-4 py-3 text-white">
            <MessageCircle className="h-4 w-4" />
            <span className="text-sm font-semibold">{t('chat.title')}</span>
            <button onClick={() => setOpen(false)} className="ml-auto rounded-lg p-1 hover:bg-white/20" aria-label="Close chat"><X className="h-4 w-4" /></button>
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto p-3">
            {msgs.map((m, i) => (
              <div key={i} className={cn('max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap',
                m.role === 'user' ? 'ml-auto bg-brand-600 text-white' : 'bg-[var(--surface-2)] text-[var(--text)]')}>
                {m.content}
              </div>
            ))}
            {busy && <div className="text-xs text-[var(--text-muted)]">{t('chat.thinking')}</div>}
            <div ref={bottomRef} />
          </div>
          <div className="flex gap-2 border-t border-[var(--border)] p-2.5">
            <input value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void send()}
              placeholder={t('chat.placeholder')} aria-label={t('chat.placeholder')}
              className="h-9 flex-1 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 text-sm outline-none focus:border-brand-500" />
            <button onClick={() => void send()} disabled={busy || !input.trim()}
              className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50" aria-label={t('chat.send')}>
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
      <button onClick={() => setOpen((v) => !v)}
        className="fixed bottom-5 right-5 z-50 flex h-13 w-13 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-teal-brand-600 text-white shadow-[var(--shadow-pop)] transition-transform hover:scale-105"
        style={{ height: 52, width: 52 }} aria-label={t('chat.title')}>
        {open ? <X className="h-5 w-5" /> : <MessageCircle className="h-5 w-5" />}
      </button>
    </>
  )
}
