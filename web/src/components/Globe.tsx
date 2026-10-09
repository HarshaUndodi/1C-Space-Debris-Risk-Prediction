import { useEffect, useRef } from 'react'
import {
  Cartesian3, Color, ImageryLayer, Ion, NearFarScalar, PointPrimitiveCollection,
  PolylineCollection, Material, TileMapServiceImageryProvider, Viewer, buildModuleUrl,
} from 'cesium'
import 'cesium/Build/Cesium/Widgets/widgets.css'
import type { CatalogObject, Conjunction, OrbitPoint } from '../types'

const ionToken = import.meta.env.VITE_CESIUM_ION_TOKEN as string | undefined
if (ionToken) Ion.defaultAccessToken = ionToken

const toCart = (o: { lat: number; lon: number; alt_km: number }) =>
  Cartesian3.fromDegrees(o.lon, o.lat, o.alt_km * 1000)

const COLORS = {
  debris: Color.fromCssColorString('#7a8594').withAlpha(0.75),
  payload: Color.WHITE.withAlpha(0.9),
  primary: Color.fromCssColorString('#22d3ee'),
  conj: Color.fromCssColorString('#ef4444'),
}

export function Globe({ objects, primary, orbit, conjunctions }: {
  objects: CatalogObject[]
  primary?: CatalogObject | null
  orbit: OrbitPoint[]
  conjunctions: Conjunction[]
}) {
  const el = useRef<HTMLDivElement>(null)
  const viewer = useRef<Viewer | null>(null)
  const points = useRef<PointPrimitiveCollection | null>(null)
  const lines = useRef<PolylineCollection | null>(null)

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
    v.scene.globe.enableLighting = false
    if (v.scene.skyAtmosphere) v.scene.skyAtmosphere.show = true
    v.camera.setView({ destination: Cartesian3.fromDegrees(77, 15, 22_000_000) })
    points.current = v.scene.primitives.add(new PointPrimitiveCollection())
    lines.current = v.scene.primitives.add(new PolylineCollection())
    viewer.current = v
    return () => { v.destroy(); viewer.current = null }
  }, [])

  // Redraw points/lines when data changes.
  useEffect(() => {
    const pc = points.current, lc = lines.current
    if (!pc || !lc) return
    pc.removeAll()
    lc.removeAll()
    const conjIds = new Set(conjunctions.map((c) => c.secondary.norad))
    for (const o of objects) {
      if (o.norad === primary?.norad || conjIds.has(o.norad)) continue
      pc.add({
        position: toCart(o),
        pixelSize: o.type === 'PAYLOAD' ? 3 : 2,
        color: o.type === 'PAYLOAD' ? COLORS.payload : COLORS.debris,
        scaleByDistance: new NearFarScalar(1e6, 1.6, 4e7, 0.8),
      })
    }
    if (orbit.length > 1) {
      lc.add({
        positions: orbit.map(toCart), width: 2,
        material: Material.fromType('Color', { color: COLORS.primary.withAlpha(0.7) }),
      })
    }
    if (primary) {
      const pp = toCart(primary)
      for (const c of conjunctions) {
        const sp = toCart(c.secondary)
        pc.add({ position: sp, pixelSize: 7, color: COLORS.conj, outlineColor: Color.WHITE, outlineWidth: 1 })
        lc.add({ positions: [pp, sp], width: 1.5, material: Material.fromType('Color', { color: COLORS.conj.withAlpha(0.8) }) })
      }
      pc.add({ position: pp, pixelSize: 10, color: COLORS.primary, outlineColor: Color.WHITE, outlineWidth: 2 })
    }
    viewer.current?.scene.requestRender()
  }, [objects, primary, orbit, conjunctions])

  return <div className="globe" ref={el} />
}
