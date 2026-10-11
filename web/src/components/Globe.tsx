import { useEffect, useRef, useState } from 'react'
import {
  Cartesian2, Cartesian3, Color, ImageryLayer, Ion, Material, NearFarScalar, PointPrimitive,
  PointPrimitiveCollection, PolylineCollection, ScreenSpaceEventHandler, ScreenSpaceEventType,
  TileMapServiceImageryProvider, Viewer, buildModuleUrl,
} from 'cesium'
import 'cesium/Build/Cesium/Widgets/widgets.css'
import { positionAt, type SimClock } from '../live'
import type { CatalogObject, Conjunction, LiveTracks, OrbitPoint, TrackObject } from '../types'

const ionToken = import.meta.env.VITE_CESIUM_ION_TOKEN as string | undefined
if (ionToken) Ion.defaultAccessToken = ionToken

const toCart = (o: { lat: number; lon: number; alt_km: number }) =>
  Cartesian3.fromDegrees(o.lon, o.lat, o.alt_km * 1000)

const COLORS = {
  debris: Color.fromCssColorString('#64748b').withAlpha(0.75),
  payload: Color.WHITE.withAlpha(0.9),
  primary: Color.fromCssColorString('#22d3ee'),
  isro: Color.fromCssColorString('#10b981'), // vibrant emerald for ISRO assets
  cosmos1408: Color.fromCssColorString('#ff4500'), // glowing neon orange for Cosmos-1408 debris
  asat: Color.fromCssColorString('#f43f5e'), // rose for Fengyun-1C / collision debris
  conj: Color.fromCssColorString('#ef4444'),
}

type PointMeta = {
  norad: number
  name: string
  type: string
  tag?: string
}

function getPointStyle(
  o: PointMeta,
  primaryNorad?: number | null,
  highlightIsro = false,
  highlightSwarm = false,
) {
  const isPrimary = o.norad === primaryNorad
  if (isPrimary) {
    return {
      pixelSize: 12,
      color: COLORS.primary,
      outlineColor: Color.WHITE,
      outlineWidth: 2,
      scaleByDistance: undefined,
    }
  }

  const isCosmos1408 = o.tag === 'cosmos-1408'
  const isAsat = o.tag === 'fengyun-1c' || o.tag === 'collision-debris'
  const isIsro = o.tag === 'isro'

  if (isCosmos1408) {
    return {
      pixelSize: highlightSwarm ? 7 : 4,
      color: COLORS.cosmos1408,
      outlineColor: highlightSwarm ? Color.YELLOW : Color.fromCssColorString('#7f1d1d'),
      outlineWidth: highlightSwarm ? 1.5 : 0,
      scaleByDistance: new NearFarScalar(1e6, 2.0, 4e7, 1.0),
    }
  }

  if (isAsat && highlightSwarm) {
    return {
      pixelSize: 4.5,
      color: COLORS.asat,
      outlineColor: Color.fromCssColorString('#fda4af'),
      outlineWidth: 1,
      scaleByDistance: new NearFarScalar(1e6, 1.6, 4e7, 0.8),
    }
  }

  if (isIsro) {
    return {
      pixelSize: highlightIsro ? 8 : 4.5,
      color: COLORS.isro,
      outlineColor: highlightIsro ? Color.WHITE : Color.TRANSPARENT,
      outlineWidth: highlightIsro ? 1.5 : 0,
      scaleByDistance: new NearFarScalar(1e6, 1.8, 4e7, 0.9),
    }
  }

  const isPayload = o.type === 'PAYLOAD'
  return {
    pixelSize: isPayload ? 3 : 2.4,
    color: isPayload ? COLORS.payload : COLORS.debris,
    outlineColor: Color.TRANSPARENT,
    outlineWidth: 0,
    scaleByDistance: new NearFarScalar(1e6, 1.6, 4e7, 0.8),
  }
}

/**
 * Cesium globe. With `tracks` + `clock`, every object is moved each frame by interpolating its SGP4
 * samples at the simulated time (real time, or warped). Without tracks, `objects` are drawn static.
 */
export function Globe({
  objects,
  tracks,
  clock,
  primaryNorad,
  orbit,
  conjunctions,
  spin,
  highlightIsro = false,
  highlightSwarm = false,
  onSelectObject,
}: {
  objects: CatalogObject[]
  tracks?: LiveTracks | null
  clock?: SimClock
  primaryNorad?: number | null
  orbit: OrbitPoint[]
  conjunctions: Conjunction[]
  spin?: boolean
  highlightIsro?: boolean
  highlightSwarm?: boolean
  onSelectObject?: (norad: number) => void
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
  const onSelectRef = useRef(onSelectObject)
  onSelectRef.current = onSelectObject
  const [hovered, setHovered] = useState<PointMeta | null>(null)

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

    // Interactive picker handler for hover inspection
    const handler = new ScreenSpaceEventHandler(v.scene.canvas)
    handler.setInputAction((movement: { endPosition: Cartesian2 }) => {
      const picked = v.scene.pick(movement.endPosition)
      if (picked && picked.primitive && (picked.primitive as unknown as { _meta?: PointMeta })._meta) {
        setHovered((picked.primitive as unknown as { _meta: PointMeta })._meta)
      } else {
        setHovered(null)
      }
    }, ScreenSpaceEventType.MOUSE_MOVE)

    handler.setInputAction((movement: { position: Cartesian2 }) => {
      const picked = v.scene.pick(movement.position)
      if (picked && picked.primitive && (picked.primitive as unknown as { _meta?: PointMeta })._meta) {
        const meta = (picked.primitive as unknown as { _meta: PointMeta })._meta
        if (onSelectRef.current) onSelectRef.current(meta.norad)
      }
    }, ScreenSpaceEventType.LEFT_CLICK)

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
    return () => {
      handler.destroy()
      v.destroy()
      viewer.current = null
    }
  }, [])

  // Moving objects (tracks) or static objects (catalog fallback).
  useEffect(() => {
    const pc = points.current
    if (!pc) return
    pc.removeAll()
    moving.current = null
    if (tracks && tracks.objects.length) {
      const pts = tracks.objects.map((o: TrackObject) => {
        const style = getPointStyle(o, primaryNorad, highlightIsro, highlightSwarm)
        const pt = pc.add({
          position: Cartesian3.ZERO,
          pixelSize: style.pixelSize,
          color: style.color,
          outlineColor: style.outlineColor,
          outlineWidth: style.outlineWidth,
          scaleByDistance: style.scaleByDistance,
        })
        ;(pt as unknown as { _meta: PointMeta })._meta = o
        return pt
      })
      moving.current = { pts, tracks }
      return
    }
    for (const o of objects) {
      const style = getPointStyle(o, primaryNorad, highlightIsro, highlightSwarm)
      const pt = pc.add({
        position: toCart(o),
        pixelSize: style.pixelSize,
        color: style.color,
        outlineColor: style.outlineColor,
        outlineWidth: style.outlineWidth,
        scaleByDistance: style.scaleByDistance,
      })
      ;(pt as unknown as { _meta: PointMeta })._meta = o
    }
  }, [tracks, objects, primaryNorad, highlightIsro, highlightSwarm])

  // Orbit trail + conjunction geometry at TCA.
  useEffect(() => {
    const mc = markers.current, lc = lines.current
    if (!mc || !lc) return
    mc.removeAll()
    lc.removeAll()
    if (orbit.length > 1) {
      lc.add({
        positions: orbit.map(toCart),
        width: 2,
        material: Material.fromType('Color', { color: COLORS.primary.withAlpha(0.65) }),
      })
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

  return (
    <div className="globe-container" style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div className="globe" ref={el} />
      {hovered && (
        <div className="globe-hud" role="status" aria-live="polite">
          <span className={`hud-badge hud-${hovered.tag ?? 'general'}`}>
            {hovered.tag === 'isro'
              ? '🇮🇳 ISRO ASSET'
              : hovered.tag === 'cosmos-1408'
              ? '🔥 COSMOS 1408 ASAT DEBRIS'
              : hovered.tag === 'fengyun-1c'
              ? '⚠️ FENGYUN-1C ASAT DEBRIS'
              : hovered.tag === 'collision-debris'
              ? '💥 COLLISION DEBRIS'
              : hovered.type}
          </span>
          <span className="hud-name mono">{hovered.name}</span>
          <span className="hud-norad mono muted">NORAD {hovered.norad}</span>
        </div>
      )}
    </div>
  )
}
