// Browser speech in/out for the voice agent. Speech recognition exists in Chrome/Edge/Safari (needs
// HTTPS or localhost); speech synthesis everywhere. A natural-sounding female voice is preferred.
import { ambient } from './ambient'

type Recognition = {
  lang: string; interimResults: boolean; continuous: boolean
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
  start: () => void; stop: () => void; abort: () => void
}

export function createRecognition(): Recognition | null {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition }
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition
  if (!Ctor) return null
  const r = new Ctor()
  r.lang = 'en-US'
  r.interimResults = true
  r.continuous = false
  return r
}

// Ordered by preference: neural/natural female voices first, then common female system voices.
const FEMALE = [
  /Microsoft (Aria|Jenny|Sonia|Libby|Natasha|Emma|Ava|Michelle|Neerja)/i, /Google UK English Female/i,
  /Samantha|Karen|Moira|Tessa|Fiona|Victoria|Serena|Allison|Ava|Susan/i, /Google US English/i, /Zira|Hazel|Heera/i, /female/i,
]
const MALE = /David|Mark|Guy|Ryan|Daniel|Alex|George|Fred|Thomas|Ravi|James|Male/i

let chosen: SpeechSynthesisVoice | null = null
function pickVoice(): SpeechSynthesisVoice | null {
  if (chosen) return chosen
  const voices = window.speechSynthesis?.getVoices() ?? []
  for (const re of FEMALE) {
    const v = voices.find((x) => re.test(x.name) && !MALE.test(x.name) && x.lang.startsWith('en'))
    if (v) return (chosen = v)
  }
  return voices.find((x) => x.lang.startsWith('en') && !MALE.test(x.name)) ?? null
}
if (typeof window !== 'undefined' && window.speechSynthesis) {
  window.speechSynthesis.onvoiceschanged = () => { chosen = null; pickVoice() }
}

export const canSpeak = () => typeof window !== 'undefined' && !!window.speechSynthesis

/** Speak text sentence by sentence (Chrome cuts off long single utterances); music ducks meanwhile. */
export function speak(text: string, onStart?: () => void, onEnd?: () => void) {
  if (!canSpeak()) { onEnd?.(); return }
  const synth = window.speechSynthesis
  synth.cancel()
  const parts = text.match(/[^.!?]+[.!?]*/g)?.map((s) => s.trim()).filter(Boolean) ?? [text]
  const voice = pickVoice()
  ambient.duck(true)
  parts.forEach((p, i) => {
    const u = new SpeechSynthesisUtterance(p)
    if (voice) u.voice = voice
    u.rate = 1.03
    u.pitch = voice ? 1.0 : 1.25 // no female voice found: lift the pitch of the default
    if (i === 0) u.onstart = () => onStart?.()
    if (i === parts.length - 1) {
      u.onend = () => { ambient.duck(false); onEnd?.() }
      u.onerror = () => { ambient.duck(false); onEnd?.() }
    }
    synth.speak(u)
  })
}

export function stopSpeaking() {
  if (canSpeak()) window.speechSynthesis.cancel()
  ambient.duck(false)
}
