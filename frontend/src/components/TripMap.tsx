// MapLibre GL map of the itinerary (F13). Numbered markers per day + route lines.
import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import type { Destination, HomeBase, ItineraryDay, UUID } from '../api'
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
  onSelectStop?: (id: UUID) => void
}

export default function TripMap({ days, destinations, homeBase, selectedDay, highlighted, onSelectStop }: Props) {
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
    home.textContent = '🏨'
    home.title = homeBase.label
    markers.current.push(new maplibregl.Marker({ element: home }).setLngLat([homeBase.lng, homeBase.lat]).addTo(m))

    const features: GeoJSON.Feature[] = []
    for (const day of visible) {
      const coords: [number, number][] = [[homeBase.lng, homeBase.lat]]
      day.stops.forEach((s, i) => {
        const d = destinations.get(s.destination_id)
        if (!d) return
        coords.push([d.lng, d.lat])
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
      coords.push([homeBase.lng, homeBase.lat])
      features.push({
        type: 'Feature',
        properties: { color: dayColor(day.day_index) },
        geometry: { type: 'LineString', coordinates: coords },
      })
    }

    const data: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features }
    const src = m.getSource('routes') as maplibregl.GeoJSONSource | undefined
    if (src) src.setData(data)
    else {
      m.addSource('routes', { type: 'geojson', data })
      m.addLayer({
        id: 'routes',
        type: 'line',
        source: 'routes',
        paint: { 'line-color': ['get', 'color'], 'line-width': 3, 'line-opacity': 0.75, 'line-dasharray': [2, 1.5] },
        layout: { 'line-cap': 'round', 'line-join': 'round' },
      })
    }

    if (!bounds.isEmpty()) m.fitBounds(bounds, { padding: 48, maxZoom: 14, duration: 400 })
  }, [days, destinations, homeBase, selectedDay, highlighted, ready, onSelectStop])

  if (failed) {
    return (
      <div className="flex h-full min-h-64 items-center justify-center rounded-xl bg-stone-100 p-6 text-center text-sm text-stone-500">
        The map couldn't load (no WebGL or no network). The timeline still shows the full plan.
      </div>
    )
  }
  return <div ref={container} className="h-full min-h-64 w-full overflow-hidden rounded-xl" />
}
