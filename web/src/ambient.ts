// Generative "deep space" ambience with the Web Audio API — no audio files, nothing to license.
// Slow detuned pad chords through a breathing low-pass filter, a sub drone, a long synthetic reverb,
// and sparse high "star" pings with echoes. Starts only from a click (browser autoplay rules).

type Chord = number[] // MIDI notes

// D minor-ish modal drift: Dm9 → B♭maj7 → Fmaj7(add9) → Cadd9/E. Slow, unresolved, spacious.
const CHORDS: Chord[] = [
  [38, 50, 57, 60, 64, 69],
  [34, 46, 53, 57, 62, 65],
  [41, 48, 55, 60, 64, 67],
  [40, 48, 55, 59, 62, 67],
]
const STAR_NOTES = [74, 76, 79, 81, 84, 86, 88]
const CHORD_SECONDS = 14

const hz = (m: number) => 440 * Math.pow(2, (m - 69) / 12)

function impulse(ctx: AudioContext, seconds = 6, decay = 2.6): AudioBuffer {
  const len = Math.floor(ctx.sampleRate * seconds)
  const buf = ctx.createBuffer(2, len, ctx.sampleRate)
  for (let ch = 0; ch < 2; ch++) {
    const d = buf.getChannelData(ch)
    for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay)
  }
  return buf
}

export class Ambient {
  private ctx: AudioContext | null = null
  private master: GainNode | null = null
  private timers: number[] = []
  private voices: { osc: OscillatorNode[]; gain: GainNode }[] = []
  playing = false

  start() {
    if (this.playing) return
    const ctx = this.ctx ?? new AudioContext()
    this.ctx = ctx
    void ctx.resume()
    const master = ctx.createGain()
    master.gain.value = 0
    master.connect(ctx.destination)
    master.gain.linearRampToValueAtTime(0.22, ctx.currentTime + 4) // slow fade-in
    this.master = master

    const reverb = ctx.createConvolver()
    reverb.buffer = impulse(ctx)
    const wet = ctx.createGain(); wet.gain.value = 0.85
    const dry = ctx.createGain(); dry.gain.value = 0.35
    reverb.connect(wet).connect(master)
    dry.connect(master)

    // Breathing low-pass on the pad bus.
    const filter = ctx.createBiquadFilter()
    filter.type = 'lowpass'; filter.frequency.value = 900; filter.Q.value = 0.7
    const lfo = ctx.createOscillator(); lfo.frequency.value = 0.045
    const lfoAmt = ctx.createGain(); lfoAmt.gain.value = 550
    lfo.connect(lfoAmt).connect(filter.frequency); lfo.start()
    filter.connect(dry); filter.connect(reverb)

    // Sub drone on D.
    const sub = ctx.createOscillator(); sub.type = 'sine'; sub.frequency.value = hz(26)
    const subGain = ctx.createGain(); subGain.gain.value = 0.18
    sub.connect(subGain).connect(master); sub.start()
    this.voices.push({ osc: [sub, lfo], gain: subGain })

    let k = 0
    const playChord = () => {
      if (!this.ctx) return
      const now = ctx.currentTime
      const chord = CHORDS[k++ % CHORDS.length]
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, now)
      gain.gain.linearRampToValueAtTime(0.055, now + 5)                       // long attack
      gain.gain.setValueAtTime(0.055, now + CHORD_SECONDS - 1)
      gain.gain.linearRampToValueAtTime(0, now + CHORD_SECONDS + 6)           // overlap into the next chord
      gain.connect(filter)
      const oscs: OscillatorNode[] = []
      for (const note of chord) {
        for (const det of [-7, 6]) {                                         // two detuned saws per note
          const o = ctx.createOscillator()
          o.type = note < 48 ? 'triangle' : 'sawtooth'
          o.frequency.value = hz(note)
          o.detune.value = det
          o.connect(gain)
          o.start(now)
          o.stop(now + CHORD_SECONDS + 6.5)
          oscs.push(o)
        }
      }
      const v = { osc: oscs, gain }
      this.voices.push(v)
      window.setTimeout(() => { this.voices = this.voices.filter((x) => x !== v) }, (CHORD_SECONDS + 7) * 1000)
    }
    playChord()
    this.timers.push(window.setInterval(playChord, CHORD_SECONDS * 1000))

    // Sparse "stars": soft sine pings with a feedback echo.
    const echo = ctx.createDelay(2); echo.delayTime.value = 0.62
    const fb = ctx.createGain(); fb.gain.value = 0.45
    echo.connect(fb).connect(echo)
    echo.connect(reverb)
    const ping = () => {
      if (!this.ctx) return
      const now = ctx.currentTime
      const o = ctx.createOscillator(); o.type = 'sine'
      o.frequency.value = hz(STAR_NOTES[Math.floor(Math.random() * STAR_NOTES.length)])
      const g = ctx.createGain()
      g.gain.setValueAtTime(0, now)
      g.gain.linearRampToValueAtTime(0.035, now + 0.02)
      g.gain.exponentialRampToValueAtTime(0.0001, now + 2.2)
      o.connect(g); g.connect(echo); g.connect(reverb)
      o.start(now); o.stop(now + 2.3)
      this.timers.push(window.setTimeout(ping, 2200 + Math.random() * 5200))
    }
    this.timers.push(window.setTimeout(ping, 3000))
    this.playing = true
  }

  /** Lower the music under the voice agent, then bring it back. */
  duck(on: boolean) {
    if (!this.ctx || !this.master) return
    const t = this.ctx.currentTime
    this.master.gain.cancelScheduledValues(t)
    this.master.gain.setValueAtTime(this.master.gain.value, t)
    this.master.gain.linearRampToValueAtTime(on ? 0.06 : 0.22, t + (on ? 0.4 : 1.6))
  }

  stop() {
    if (!this.playing || !this.ctx || !this.master) return
    const ctx = this.ctx
    this.timers.forEach((t) => { clearInterval(t); clearTimeout(t) })
    this.timers = []
    this.master.gain.cancelScheduledValues(ctx.currentTime)
    this.master.gain.setValueAtTime(this.master.gain.value, ctx.currentTime)
    this.master.gain.linearRampToValueAtTime(0, ctx.currentTime + 1.5)  // fade out, then free everything
    const voices = this.voices
    this.voices = []
    const old = this.ctx
    this.ctx = null
    this.master = null
    this.playing = false
    window.setTimeout(() => { voices.forEach((v) => v.osc.forEach((o) => { try { o.stop() } catch { /* already stopped */ } })); void old.close() }, 1700)
  }
}

export const ambient = new Ambient()
