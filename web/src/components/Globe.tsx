import { useEffect, useRef } from 'react'
import {
  Cartesian3, Color, ImageryLayer, Ion, Material, NearFarScalar, PointPrimitive, PointPrimitiveCollection,
  PolylineCollection, TileMapServiceImageryProvider, Viewer, buildModuleUrl,
} from 'cesium'
import 'cesium/Build/Cesium/Widgets/widgets.css'
import { positionAt, type SimClock } from '../live'
import type { CatalogObject, Conjunction, LiveTracks, OrbitPoint } from '../types'

const ionToken = import.meta.env.VITE_CESIUM_ION_TOKEN as string | undefined
if (ionToken) Ion.defaultAccessToken = ionToken

const toCart = (o: { lat: number; lon: number; alt_km: number }) =>
  Cartesian3.fromDegrees(o.lon, o.lat, o.alt_km * 1000)

const COLORS = {
  debris: Color.fromCssColorString('#7a8594').withAlpha(0.8),
  payload: Color.WHITE.withAlpha(0.9),
  primary: Color.fromCssColorString('#22d3ee'),
  conj: Color.fromCssColorString('#ef4444'),
}

/**
 * Cesium globe. With `tracks` + `clock`, every object is moved each frame by interpolating its SGP4
 * samples at the simulated time (real time, or warped). Without tracks, `objects` are drawn static.
 */
export function Globe({ objects, tracks, clock, primaryNorad, orbit, conjunctions, spin }: {
  objects: CatalogObject[]
  tracks?: LiveTracks | null
  clock?: SimClock
  primaryNorad?: number | null
  orbit: OrbitPoint[]
  conjunctions: Conjunction[]
  spin?: boolean
}) {
  const el = useRef<HTMLDivElement>(null)
  const viewer = useRef<Viewer | null>(null)
  const points = useRef<PointPrimitiveCollection | null>(null)
  const markers = useRef<PointPrimitiveCollection | null>(null)
  const lines = useRef<PolylineCollection | null>(null)
  const moving = useRef<{ pts: PointPrimitive[]; tracks: LiveTracks } | null>(null)
  const clockRef = useRef(clock)
  clockRef.current = clock
  const spinRef = useRef(spin)
  spinRef.current = spin

  // Create the viewer once. Bundled Natural Earth II imagery, no terrain -> works offline, no Ion account.
  useEffect(() => {
    if (!el.current) return
    const v = new Viewer(el.current, {
      baseLayer: ImageryLayer.fromProviderAsync(
        TileMapServiceImageryProvider.fromUrl(buildModuleUrl('Assets/Textures/NaturalEarthII')), {}),
      baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false,
      navigationHelpButton: false, animation: false, timeline: false, fullscreenButton: false,
      infoBox: false, selectionIndicator: false,
    })
    v.scene.backgroundColor = Color.fromCssColorString('#05070b')
    if (v.scene.skyAtmosphere) v.scene.skyAtmosphere.show = true
    v.camera.setView({ destination: Cartesian3.fromDegrees(77, 15, 22_000_000) })
    points.current = v.scene.primitives.add(new PointPrimitiveCollection())
    markers.current = v.scene.primitives.add(new PointPrimitiveCollection())
    lines.current = v.scene.primitives.add(new PolylineCollection())
    viewer.current = v

    // Per-frame: move every tracked object to its interpolated position at sim time; slow idle spin.
    const scratch = [0, 0, 0]
    const cart = new Cartesian3()
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    let lastSpin = performance.now()
    const onFrame = () => {
      const m = moving.current
      const c = clockRef.current
      if (m && c) {
        const t = c.now()
        for (let i = 0; i < m.pts.length; i++) {
          const p = positionAt(m.tracks, i, t, scratch)
          if (!p) continue
          Cartesian3.fromElements(p[0] * 1000, p[1] * 1000, p[2] * 1000, cart)
          m.pts[i].position = cart
        }
      }
      const now = performance.now()
      if (spinRef.current && !reduce) v.scene.camera.rotate(Cartesian3.UNIT_Z, -0.000035 * (now - lastSpin))
      lastSpin = now
    }
    v.scene.preRender.addEventListener(onFrame)
    // Any user interaction stops the idle spin.
    const stop = () => { spinRef.current = false }
    el.current.addEventListener('pointerdown', stop)
    el.current.addEventListener('wheel', stop, { passive: true })
    return () => { v.destroy(); viewer.current = null }
  }, [])

  // Moving objects (tracks) or static objects (catalog fallback).
  useEffect(() => {
    const pc = points.current
    if (!pc) return
    pc.removeAll()
    moving.current = null
    if (tracks && tracks.objects.length) {
      const pts = tracks.objects.map((o) => {
        const isPrimary = o.norad === primaryNorad
        return pc.add({
          position: Cartesian3.ZERO,
          pixelSize: isPrimary ? 11 : o.type === 'PAYLOAD' ? 3 : 2.4,
          color: isPrimary ? COLORS.primary : o.type === 'PAYLOAD' ? COLORS.payload : COLORS.debris,
          outlineColor: Color.WHITE, outlineWidth: isPrimary ? 2 : 0,
          scaleByDistance: isPrimary ? undefined : new NearFarScalar(1e6, 1.6, 4e7, 0.8),
        })
      })
      moving.current = { pts, tracks }
      return
    }
    for (const o of objects) {
      pc.add({
        position: toCart(o),
        pixelSize: o.norad === primaryNorad ? 11 : o.type === 'PAYLOAD' ? 3 : 2,
        color: o.norad === primaryNorad ? COLORS.primary : o.type === 'PAYLOAD' ? COLORS.payload : COLORS.debris,
        scaleByDistance: new NearFarScalar(1e6, 1.6, 4e7, 0.8),
      })
    }
  }, [tracks, objects, primaryNorad])

  // Orbit trail + conjunction geometry at TCA.
  useEffect(() => {
    const mc = markers.current, lc = lines.current
    if (!mc || !lc) return
    mc.removeAll()
    lc.removeAll()
    if (orbit.length > 1) {
      lc.add({ positions: orbit.map(toCart), width: 2,
        material: Material.fromType('Color', { color: COLORS.primary.withAlpha(0.65) }) })
    }
    for (const c of conjunctions) {
      const sp = toCart(c.secondary)
      mc.add({ position: sp, pixelSize: 8, color: COLORS.conj, outlineColor: Color.WHITE, outlineWidth: 1 })
      if (c.primary_at_tca) {
        const pp = toCart(c.primary_at_tca)
        mc.add({ position: pp, pixelSize: 5, color: COLORS.primary.withAlpha(0.7) })
        lc.add({ positions: [pp, sp], width: 2, material: Material.fromType('Color', { color: COLORS.conj.withAlpha(0.9) }) })
      }
    }
  }, [orbit, conjunctions])

  return <div className="globe" ref={el} />
}
