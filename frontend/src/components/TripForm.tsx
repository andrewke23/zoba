// Trip configuration form (F02): city, dates, daily window, home base.
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import maplibregl from 'maplibre-gl'
import type { City, TripInput } from '../api'
import { Button, ErrorBox, Field, Input, Select } from './ui'

const STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL ?? 'https://tiles.openfreemap.org/styles/liberty'
const GEOCODER_URL = import.meta.env.VITE_GEOCODER_URL ?? 'https://nominatim.openstreetmap.org/reverse'
const SEARCH_URL = import.meta.env.VITE_GEOCODER_SEARCH_URL ?? GEOCODER_URL.replace(/\/reverse$/, '/search')
/** Wait this long after the last keystroke before searching (Nominatim allows ~1 request/s). */
const SEARCH_DEBOUNCE_MS = 700
/** Search within this many degrees of the city center so matches stay in the trip's city. */
const SEARCH_RADIUS_DEG = 0.35

interface NominatimPlace {
  name?: string
  display_name?: string
  address?: Record<string, string>
  lat?: string
  lon?: string
}

interface PlaceMatch {
  label: string
  lat: number
  lng: number
}

/** A short label like "Hotel — 151 E Wacker Dr". */
function shortLabel(place: NominatimPlace): string | null {
  const a = place.address ?? {}
  const street = [a.house_number, a.road].filter(Boolean).join(' ')
  if (place.name && street) return `${place.name} — ${street}`
  return place.name || street || place.display_name?.split(',').slice(0, 2).join(',').trim() || null
}

/** Reverse-geocode a point to a short label. */
async function reverseGeocode(lat: number, lng: number, signal: AbortSignal): Promise<string | null> {
  const url = `${GEOCODER_URL}?format=jsonv2&zoom=18&lat=${lat}&lon=${lng}`
  const res = await fetch(url, { signal, headers: { Accept: 'application/json' } })
  if (!res.ok) return null
  return shortLabel(await res.json())
}

/** Find places matching typed text near the city center (up to 5). */
async function searchPlaces(query: string, near: { lat: number; lng: number }, signal: AbortSignal): Promise<PlaceMatch[]> {
  const r = SEARCH_RADIUS_DEG
  const viewbox = [near.lng - r, near.lat + r, near.lng + r, near.lat - r].join(',')
  const params = new URLSearchParams({ format: 'jsonv2', addressdetails: '1', limit: '5', bounded: '1', viewbox, q: query })
  const res = await fetch(`${SEARCH_URL}?${params}`, { signal, headers: { Accept: 'application/json' } })
  if (!res.ok) return []
  const places: NominatimPlace[] = await res.json()
  return places.flatMap((p) => {
    const label = shortLabel(p)
    const lat = Number(p.lat)
    const lng = Number(p.lon)
    return label && Number.isFinite(lat) && Number.isFinite(lng) ? [{ label, lat, lng }] : []
  })
}

interface Props {
  cities: City[]
  initial?: TripInput
  submitLabel: string
  onSubmit: (input: TripInput) => Promise<void>
}

export default function TripForm({ cities, initial, submitLabel, onSubmit }: Props) {
  const [form, setForm] = useState<TripInput>(
    initial ?? {
      name: '',
      city_id: cities[0]?.city_id ?? '',
      start_date: '',
      end_date: '',
      day_start: '09:00',
      day_end: '21:00',
      home_base: {
        label: '',
        lat: cities[0]?.center[1] ?? 0,
        lng: cities[0]?.center[0] ?? 0,
      },
    },
  )
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [locating, setLocating] = useState(false)
  const lookup = useRef<AbortController | null>(null)
  const [matches, setMatches] = useState<PlaceMatch[]>([])
  const search = useRef<{ timer?: ReturnType<typeof setTimeout>; ctrl?: AbortController }>({})
  const set = <K extends keyof TripInput>(k: K, v: TripInput[K]) => setForm((f) => ({ ...f, [k]: v }))

  useEffect(
    () => () => {
      lookup.current?.abort()
      clearTimeout(search.current.timer)
      search.current.ctrl?.abort()
    },
    [],
  )

  function cancelSearch() {
    clearTimeout(search.current.timer)
    search.current.ctrl?.abort()
    setMatches([])
  }

  // Typing a hotel or address searches near the city center after a pause and
  // offers matches; picking one moves the pin there.
  function typeHomeBase(label: string) {
    setForm((f) => ({ ...f, home_base: { ...f.home_base, label } }))
    cancelSearch()
    if (label.trim().length < 3) return
    const c = cities.find((x) => x.city_id === form.city_id)
    const near = c ? { lat: c.center[1], lng: c.center[0] } : { lat: form.home_base.lat, lng: form.home_base.lng }
    search.current.timer = setTimeout(async () => {
      const ctrl = new AbortController()
      search.current.ctrl = ctrl
      try {
        const found = await searchPlaces(label.trim(), near, ctrl.signal)
        if (!ctrl.signal.aborted) setMatches(found)
      } catch {
        // Offline or rate-limited: the map tap still works.
      }
    }, SEARCH_DEBOUNCE_MS)
  }

  function pickMatch(match: PlaceMatch) {
    cancelSearch()
    lookup.current?.abort()
    setForm((f) => ({ ...f, home_base: { label: match.label, lat: match.lat, lng: match.lng } }))
  }

  // Moving the pin fills the home-base label with the address under it; a newer
  // tap cancels any lookup still in flight so stale answers never win.
  async function placeHomeBase(lat: number, lng: number) {
    cancelSearch()
    setForm((f) => ({ ...f, home_base: { ...f.home_base, lat, lng } }))
    lookup.current?.abort()
    const ctrl = new AbortController()
    lookup.current = ctrl
    setLocating(true)
    try {
      const label = await reverseGeocode(lat, lng, ctrl.signal)
      if (label) setForm((f) => ({ ...f, home_base: { ...f.home_base, label } }))
    } catch {
      // Offline or rate-limited: keep whatever the user typed.
    } finally {
      if (lookup.current === ctrl) setLocating(false)
    }
  }

  function changeCity(city_id: string) {
    const c = cities.find((x) => x.city_id === city_id)
    setForm((f) => ({ ...f, city_id, home_base: c ? { ...f.home_base, lat: c.center[1], lng: c.center[0] } : f.home_base }))
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (form.end_date < form.start_date) return setError('End date must be on or after the start date.')
    if (form.day_end <= form.day_start) return setError('Daily end time must be after the start time.')
    setPending(true)
    try {
      await onSubmit(form)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save trip')
    } finally {
      setPending(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <ErrorBox error={error} />
      <Field label="Trip name">
        <Input required placeholder="e.g. Chicago fall weekend" value={form.name} onChange={(e) => set('name', e.target.value)} />
      </Field>
      <Field label="City" hint="Destinations come from this city's curated catalog.">
        <Select value={form.city_id} onChange={(e) => changeCity(e.target.value)}>
          {cities.map((c) => (
            <option key={c.city_id} value={c.city_id}>
              {c.name}
            </option>
          ))}
        </Select>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Start date">
          <Input type="date" required value={form.start_date} onChange={(e) => set('start_date', e.target.value)} />
        </Field>
        <Field label="End date">
          <Input type="date" required min={form.start_date} value={form.end_date} onChange={(e) => set('end_date', e.target.value)} />
        </Field>
        <Field label="Day starts">
          <Input type="time" required value={form.day_start} onChange={(e) => set('day_start', e.target.value)} />
        </Field>
        <Field label="Day ends">
          <Input type="time" required value={form.day_end} onChange={(e) => set('day_end', e.target.value)} />
        </Field>
      </div>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-stone-700">Home base</legend>
        <div className="relative">
          <Input
            required
            autoComplete="off"
            placeholder="Hotel or address, e.g. Hotel — 151 E Wacker Dr"
            value={form.home_base.label}
            onChange={(e) => typeHomeBase(e.target.value)}
            onBlur={() => setMatches([])}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setMatches([])
              if (e.key === 'Enter' && matches.length) {
                // Pick the top match instead of submitting the form.
                e.preventDefault()
                pickMatch(matches[0])
              }
            }}
          />
          {matches.length > 0 && (
            <ul
              role="listbox"
              aria-label="Matching places"
              className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-stone-200 bg-white shadow-lg"
            >
              {matches.map((m) => (
                <li key={`${m.lat},${m.lng},${m.label}`}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={false}
                    className="block w-full px-3 py-2 text-left text-sm hover:bg-stone-100"
                    // mousedown, not click: the input's blur would hide the list first.
                    onMouseDown={(e) => {
                      e.preventDefault()
                      pickMatch(m)
                    }}
                  >
                    {m.label}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <p className="text-xs text-stone-500">
          Type a hotel or address and pick a match, or tap the map. Every day starts and ends here.
        </p>
        <HomeBasePicker lat={form.home_base.lat} lng={form.home_base.lng} onChange={placeHomeBase} />
        <p className="text-xs text-stone-400">
          {form.home_base.lat.toFixed(5)}, {form.home_base.lng.toFixed(5)}
          {locating && ' · Looking up address…'}
        </p>
      </fieldset>
      <Button type="submit" className="w-full sm:w-auto" loading={pending}>
        {submitLabel}
      </Button>
    </form>
  )
}

function HomeBasePicker({ lat, lng, onChange }: { lat: number; lng: number; onChange: (lat: number, lng: number) => void }) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const marker = useRef<maplibregl.Marker | null>(null)
  const cb = useRef(onChange)
  cb.current = onChange
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!el.current) return
    try {
      const m = new maplibregl.Map({ container: el.current, style: STYLE_URL, center: [lng, lat], zoom: 12, attributionControl: { compact: true } })
      marker.current = new maplibregl.Marker({ color: '#256c69', draggable: true }).setLngLat([lng, lat]).addTo(m)
      marker.current.on('dragend', () => {
        const p = marker.current!.getLngLat()
        cb.current(p.lat, p.lng)
      })
      m.on('click', (e) => cb.current(e.lngLat.lat, e.lngLat.lng))
      map.current = m
      return () => m.remove()
    } catch {
      setFailed(true)
    }
    // Map is created once; position updates are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    marker.current?.setLngLat([lng, lat])
    const m = map.current
    if (m && !m.getBounds().contains([lng, lat])) m.flyTo({ center: [lng, lat] })
  }, [lat, lng])

  if (failed) return <p className="text-xs text-stone-500">Map unavailable — the city center is used as the home base.</p>
  return <div ref={el} className="h-56 w-full overflow-hidden rounded-lg border border-stone-200" />
}
