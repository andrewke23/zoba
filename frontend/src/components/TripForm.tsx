// Trip configuration form (F02): city, dates, daily window, home base.
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import maplibregl from 'maplibre-gl'
import type { City, TripInput } from '../api'
import { Button, ErrorBox, Field, Input, Select } from './ui'

const STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL ?? 'https://tiles.openfreemap.org/styles/liberty'

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
  const set = <K extends keyof TripInput>(k: K, v: TripInput[K]) => setForm((f) => ({ ...f, [k]: v }))

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
        <Input
          required
          placeholder="Hotel or address, e.g. Hotel — 151 E Wacker Dr"
          value={form.home_base.label}
          onChange={(e) => set('home_base', { ...form.home_base, label: e.target.value })}
        />
        <p className="text-xs text-stone-500">Tap the map to place your home base. Every day starts and ends here.</p>
        <HomeBasePicker
          lat={form.home_base.lat}
          lng={form.home_base.lng}
          onChange={(lat, lng) => setForm((f) => ({ ...f, home_base: { ...f.home_base, lat, lng } }))}
        />
        <p className="text-xs text-stone-400">
          {form.home_base.lat.toFixed(5)}, {form.home_base.lng.toFixed(5)}
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
