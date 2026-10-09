import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from '../api'
import { go, type Route } from '../router'
import { canSpeak, createRecognition, speak, stopSpeaking } from '../voice'

type Turn = { role: 'user' | 'assistant'; text: string; source?: 'claude' | 'rules'; eventIds?: string[] }
type Mode = 'idle' | 'listening' | 'thinking' | 'speaking'

/** Nova: a voice agent for status updates and decision support, grounded in OrbitGuard's data. */
export function VoiceAgent({ route }: { route: Route }) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>('idle')
  const [turns, setTurns] = useState<Turn[]>([])
  const [interim, setInterim] = useState('')
  const [draft, setDraft] = useState('')
  const [voiceOn, setVoiceOn] = useState(true)
  const greeted = useRef(false)
  const rec = useRef<ReturnType<typeof createRecognition>>(null)
  const logEnd = useRef<HTMLDivElement>(null)
  const turnsRef = useRef<Turn[]>([])
  turnsRef.current = turns
  const micSupported = typeof window !== 'undefined' && !!createRecognition()

  useEffect(() => { logEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [turns, interim, mode])

  const ask = async (text: string) => {
    const q = text.trim()
    if (!q) return
    stopSpeaking()
    const history = turnsRef.current.map(({ role, text: t }) => ({ role, text: t }))
    setTurns((t) => [...t, { role: 'user', text: q }])
    setMode('thinking')
    try {
      const r = await api.agent(q, history)
      setTurns((t) => [...t, { role: 'assistant', text: r.reply, source: r.source, eventIds: r.event_ids }])
      if (voiceOn && canSpeak()) speak(r.reply, () => setMode('speaking'), () => setMode('idle'))
      else setMode('idle')
    } catch (e) {
      setTurns((t) => [...t, { role: 'assistant', text: `I couldn't reach OrbitGuard: ${errorMessage(e)}` }])
      setMode('idle')
    }
  }

  // First open: Nova introduces herself with a spoken status update.
  useEffect(() => {
    if (open && !greeted.current) {
      greeted.current = true
      void ask('Hi Nova, give me a status update.')
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const listen = () => {
    if (mode === 'listening') { rec.current?.stop(); return }
    stopSpeaking()
    const r = createRecognition()
    if (!r) return
    rec.current = r
    let final = ''
    r.onresult = (e) => {
      let text = ''
      for (let i = 0; i < e.results.length; i++) {
        text += e.results[i][0].transcript
        if (e.results[i].isFinal) final = text
      }
      setInterim(text)
    }
    r.onend = () => {
      setInterim('')
      const said = final.trim()
      if (said) void ask(said)
      else setMode('idle')
    }
    r.onerror = (e) => {
      setInterim('')
      setMode('idle')
      if (e.error === 'not-allowed') {
        setTurns((t) => [...t, { role: 'assistant', text: 'Microphone access is blocked. Allow it in the address bar, or type your question.' }])
      }
    }
    setMode('listening')
    r.start()
  }

  const eventHere = route.page === 'alert' ? route.id : null
  const chips = [
    'Status update',
    eventHere ? `Brief me on event ${eventHere.replace(/^live-.*/, 'this live conjunction')}` : 'What is the top threat?',
    eventHere && !eventHere.startsWith('live-') ? `Should we maneuver for event ${eventHere}?` : 'Should we maneuver for the top alert?',
    'Any live close approaches?',
    'How accurate is the model?',
  ]

  return (
    <>
      <button className={`nova-orb ${mode} ${open ? 'open' : ''}`} onClick={() => setOpen(!open)}
        aria-label={open ? 'Close Nova voice assistant' : 'Open Nova voice assistant'} aria-expanded={open}>
        <span className="orb-core" />
        <span className="orb-ring" />
        <span className="orb-label">NOVA</span>
      </button>

      {open && (
        <section className="nova-panel" aria-label="Nova voice assistant">
          <header className="nova-head">
            <div>
              <div className="nova-title">Nova <span className="muted">· OrbitGuard voice assistant</span></div>
              <div className={`nova-state ${mode}`}>
                {mode === 'listening' ? 'Listening…' : mode === 'thinking' ? 'Checking the data…'
                  : mode === 'speaking' ? 'Speaking' : 'Ask me anything about the alerts'}
              </div>
            </div>
            <div className="nova-head-actions">
              {canSpeak() && (
                <button className="ghost small-btn" onClick={() => { setVoiceOn(!voiceOn); stopSpeaking(); setMode('idle') }}
                  aria-pressed={voiceOn}>{voiceOn ? 'Voice on' : 'Voice off'}</button>
              )}
              <button className="ghost small-btn" onClick={() => { stopSpeaking(); setOpen(false) }} aria-label="Close">✕</button>
            </div>
          </header>

          <div className="nova-log" aria-live="polite">
            {turns.map((t, i) => (
              <div key={i} className={`bubble ${t.role}`}>
                <p>{t.text}</p>
                {t.role === 'assistant' && (t.eventIds?.length || t.source) ? (
                  <div className="bubble-meta">
                    {t.eventIds?.filter((id) => !(route.page === 'alert' && route.id === id)).map((id) => (
                      <button key={id} className="link-chip" onClick={() => go.alert(id)}>Open event {id} →</button>
                    ))}
                    {t.source && <span className="src">{t.source === 'claude' ? 'Claude · tools' : 'rule-based'}</span>}
                    {i === turns.length - 1 && canSpeak() && mode === 'idle' && (
                      <button className="link-chip" onClick={() => speak(t.text, () => setMode('speaking'), () => setMode('idle'))}>Replay ▶</button>
                    )}
                  </div>
                ) : null}
              </div>
            ))}
            {interim && <div className="bubble user interim"><p>{interim}</p></div>}
            {mode === 'thinking' && <div className="bubble assistant typing"><span /><span /><span /></div>}
            <div ref={logEnd} />
          </div>

          <div className="nova-chips">
            {chips.map((c) => <button key={c} className="chip-btn" onClick={() => void ask(c)} disabled={mode === 'thinking'}>{c}</button>)}
          </div>

          <form className="nova-input" onSubmit={(e) => { e.preventDefault(); void ask(draft); setDraft('') }}>
            {micSupported && (
              <button type="button" className={`mic ${mode === 'listening' ? 'live' : ''}`} onClick={listen}
                aria-label={mode === 'listening' ? 'Stop listening' : 'Speak to Nova'} disabled={mode === 'thinking'}>
                <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                  <path fill="currentColor" d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z" />
                </svg>
              </button>
            )}
            <input id="nova-input" value={draft} onChange={(e) => setDraft(e.target.value)}
              placeholder={micSupported ? 'Tap the mic or type a question' : 'Type a question'} autoComplete="off" />
            <button type="submit" className="send" disabled={!draft.trim() || mode === 'thinking'}>Ask</button>
          </form>
        </section>
      )}
    </>
  )
}
