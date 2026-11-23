// MapLibre GL map of the itinerary (F13). Numbered markers per day + the street
// route of every leg (walking dotted, taxi/transit solid), from the routing service.
import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import type { Destination, HomeBase, ItineraryDay, RouteLeg, UUID } from '../api'
import { dayColor } from '../lib/format'

// Free vector tiles, no API key. Swap for a self-hosted style in production.
const STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL ?? 'https://tiles.openfreemap.org/styles/liberty'

interface Props {
  days: ItineraryDay[]
  destinations: Map<UUID, Destination>
  homeBase: HomeBase
  /** null = show all days */
  selectedDay: number | null
  highlighted: UUID | null
  /** Street paths per leg; null while loading or if routing is unavailable (no lines drawn). */
  routes: RouteLeg[] | null
  onSelectStop?: (id: UUID) => void
}

const RIDE_LAYER = 'routes-ride'
const WALK_LAYER = 'routes-walk'

export default function TripMap({ days, destinations, homeBase, selectedDay, highlighted, routes, onSelectStop }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const markers = useRef<maplibregl.Marker[]>([])
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!container.current) return
    let m: maplibregl.Map
    try {
      m = new maplibregl.Map({
        container: container.current,
        style: STYLE_URL,
        center: [homeBase.lng, homeBase.lat],
        zoom: 12,
        attributionControl: { compact: true },
      })
    } catch {
      setFailed(true) // e.g. WebGL unavailable
      return
    }
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    m.on('load', () => setReady(true))
    m.on('error', (e) => {
      if (!m.isStyleLoaded() && String(e.error?.message ?? '').includes('style')) setFailed(true)
    })
    map.current = m
    return () => {
      m.remove()
      map.current = null
      setReady(false)
    }
  }, [homeBase.lat, homeBase.lng])

  useEffect(() => {
    const m = map.current
    if (!m || !ready) return

    markers.current.forEach((mk) => mk.remove())
    markers.current = []

    const visible = days.filter((d) => selectedDay === null || d.day_index === selectedDay)
    const bounds = new maplibregl.LngLatBounds([homeBase.lng, homeBase.lat], [homeBase.lng, homeBase.lat])

    const home = document.createElement('div')
    home.className = 'flex size-8 items-center justify-center rounded-full bg-stone-900 text-base shadow-lg ring-2 ring-white'
    home.textContent = '🏠'
    home.title = homeBase.label
    markers.current.push(new maplibregl.Marker({ element: home }).setLngLat([homeBase.lng, homeBase.lat]).addTo(m))

    for (const day of visible) {
      day.stops.forEach((s, i) => {
        const d = destinations.get(s.destination_id)
        if (!d) return
        bounds.extend([d.lng, d.lat])
        const el = document.createElement('button')
        el.type = 'button'
        const isHi = highlighted === s.destination_id
        el.className = `flex items-center justify-center rounded-full text-xs font-bold text-white shadow-md ring-2 ring-white transition-transform ${isHi ? 'size-9 scale-110 z-10' : 'size-7'}`
        el.style.backgroundColor = dayColor(day.day_index)
        el.textContent = s.locked ? '🔒' : String(i + 1)
        el.title = `Day ${day.day_index + 1} · ${i + 1}. ${d.name}`
        el.setAttribute('aria-label', el.title)
        el.addEventListener('click', () => onSelectStop?.(s.destination_id))
        markers.current.push(new maplibregl.Marker({ element: el }).setLngLat([d.lng, d.lat]).addTo(m))
      })
    }

    const visibleDays = new Set(visible.map((d) => d.day_index))
    const features: GeoJSON.Feature[] = (routes ?? [])
      .filter((leg) => visibleDays.has(leg.day_index) && leg.coordinates.length >= 2)
      .map((leg) => {
        leg.coordinates.forEach((c) => bounds.extend(c))
        return {
          type: 'Feature',
          properties: { color: dayColor(leg.day_index), mode: leg.mode },
          geometry: { type: 'LineString', coordinates: leg.coordinates },
        }
      })

    const data: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features }
    const src = m.getSource('routes') as maplibregl.GeoJSONSource | undefined
    if (src) src.setData(data)
    else {
      m.addSource('routes', { type: 'geojson', data })
      // Line dash patterns can't vary per feature, so walking and riding are two layers.
      m.addLayer({
        id: RIDE_LAYER,
        type: 'line',
        source: 'routes',
        filter: ['!=', ['get', 'mode'], 'walk'],
        paint: { 'line-color': ['get', 'color'], 'line-width': 4, 'line-opacity': 0.8 },
        layout: { 'line-cap': 'round', 'line-join': 'round' },
      })
      m.addLayer({
        id: WALK_LAYER,
        type: 'line',
        source: 'routes',
        filter: ['==', ['get', 'mode'], 'walk'],
        paint: { 'line-color': ['get', 'color'], 'line-width': 3.5, 'line-opacity': 0.9, 'line-dasharray': [0.2, 1.6] },
        layout: { 'line-cap': 'round', 'line-join': 'round' },
      })
    }

    if (!bounds.isEmpty()) m.fitBounds(bounds, { padding: 48, maxZoom: 14, duration: 400 })
  }, [days, destinations, homeBase, selectedDay, highlighted, routes, ready, onSelectStop])

  if (failed) {
    return (
      <div className="flex h-full min-h-64 items-center justify-center rounded-xl bg-stone-100 p-6 text-center text-sm text-stone-500">
        The map couldn't load (no WebGL or no network). The timeline still shows the full plan.
      </div>
    )
  }
  return (
    <div className="relative h-full min-h-64 w-full">
      <div ref={container} className="h-full w-full overflow-hidden rounded-xl" />
      <div className="pointer-events-none absolute bottom-2 left-2 flex items-center gap-3 rounded-md bg-white/90 px-2 py-1 text-[11px] text-stone-600 shadow-sm">
        <span className="flex items-center gap-1">
          <svg width="22" height="4" aria-hidden="true">
            <line x1="2" y1="2" x2="20" y2="2" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeDasharray="0.5 4.5" />
          </svg>
          Walk
        </span>
        <span className="flex items-center gap-1">
          <svg width="22" height="4" aria-hidden="true">
            <line x1="2" y1="2" x2="20" y2="2" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
          </svg>
          Transit / taxi
        </span>
      </div>
    </div>
  )
}
