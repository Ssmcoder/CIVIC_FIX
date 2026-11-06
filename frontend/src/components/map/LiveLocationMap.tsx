import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { Crosshair, Navigation, Loader2, LocateFixed } from 'lucide-react'
import { Button, Input } from '../ui/primitives'

/**
 * LiveLocationMap — Leaflet + OSM + Nominatim.
 * watchPosition with high accuracy, pulsing marker, draggable pin,
 * click-to-set, reverse geocoding debounced to <=1 req/s (Nominatim policy).
 */

const TILE_URL = (import.meta.env.VITE_OSM_TILE_URL as string | undefined)
  || 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
const NOMINATIM = (import.meta.env.VITE_NOMINATIM_URL as string | undefined)
  || 'https://nominatim.openstreetmap.org'

export interface LocState {
  lat: number | null; lon: number | null; accuracy: number | null
  address: string; confirmed: boolean
  status: 'idle' | 'locating' | 'locked' | 'denied' | 'manual'
}

const pinIcon = L.divIcon({
  className: 'pulse-marker',
  html: '<div style="width:18px;height:18px;border-radius:50%;background:#059669;border:3px solid #fff;box-shadow:0 1px 6px rgba(0,0,0,.4)"></div>',
  iconSize: [18, 18], iconAnchor: [9, 9],
})

let lastGeoCall = 0
const geoCache = new Map<string, string>()

async function reverseGeocode(lat: number, lon: number): Promise<string> {
  const key = `${lat.toFixed(4)},${lon.toFixed(4)}`
  const hit = geoCache.get(key)
  if (hit) return hit
  // Nominatim usage policy: max 1 req/s — enforce client-side
  const wait = 1000 - (Date.now() - lastGeoCall)
  if (wait > 0) await new Promise((r) => setTimeout(r, wait))
  lastGeoCall = Date.now()
  try {
    const r = await fetch(`${NOMINATIM}/reverse?format=jsonv2&lat=${lat}&lon=${lon}&zoom=16&accept-language=en`, {
      headers: { 'User-Agent': 'CrowdResolve/1.0 (civic-tech demo)' },
    })
    if (!r.ok) return ''
    const j = await r.json()
    const addr = j.address || {}
    const name = [addr.road || addr.neighbourhood || addr.suburb, addr.city || addr.town || addr.village, addr.state]
      .filter(Boolean).join(', ')
    const out = name || j.display_name?.split(',').slice(0, 3).join(',') || ''
    geoCache.set(key, out)
    return out
  } catch {
    return ''
  }
}

async function forwardGeocode(q: string): Promise<{ lat: number; lon: number; name: string } | null> {
  const wait = 1000 - (Date.now() - lastGeoCall)
  if (wait > 0) await new Promise((r) => setTimeout(r, wait))
  lastGeoCall = Date.now()
  try {
    const r = await fetch(`${NOMINATIM}/search?format=jsonv2&q=${encodeURIComponent(q)}&limit=1&accept-language=en`, {
      headers: { 'User-Agent': 'CrowdResolve/1.0 (civic-tech demo)' },
    })
    if (!r.ok) return null
    const j = await r.json()
    if (!j[0]) return null
    return { lat: parseFloat(j[0].lat), lon: parseFloat(j[0].lon), name: j[0].display_name }
  } catch {
    return null
  }
}

function MapController({ loc, onPick, follow }: { loc: LocState; onPick: (lat: number, lon: number, acc: number | null) => void; follow: React.MutableRefObject<boolean> }) {
  const map = useMap()
  useMapEvents({
    click(e) { onPick(e.latlng.lat, e.latlng.lng, null); follow.current = false },
  })
  useEffect(() => {
    if (loc.lat != null && loc.lon != null && follow.current) {
      map.flyTo([loc.lat, loc.lon], Math.max(map.getZoom(), 17), { duration: 0.8 })
    }
  }, [loc.lat, loc.lon, map, follow])
  return null
}

export default function LiveLocationMap({ loc, onChange }: { loc: LocState; onChange: Dispatch<SetStateAction<LocState>> }) {
  const [query, setQuery] = useState('')
  const [geoBusy, setGeoBusy] = useState(false)
  const [geoErr, setGeoErr] = useState('')
  const follow = useRef(true)
  const defaultCenter: [number, number] = [20.2969, 85.8242] // Bhubaneswar

  const setPos = useCallback((lat: number, lon: number, acc: number | null) => {
    onChange({ ...loc, lat, lon, accuracy: acc, status: 'locked', confirmed: false })
    void reverseGeocode(lat, lon).then((addr) => {
      if (addr) onChange((prev: LocState) => ({ ...prev, lat, lon, accuracy: acc, address: addr, status: 'locked' }))
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loc, onChange])

  const useGps = useCallback(() => {
    if (!navigator.geolocation) { onChange({ ...loc, status: 'denied' }); return }
    setGeoBusy(true); setGeoErr('')
    onChange({ ...loc, status: 'locating' })
    navigator.geolocation.watchPosition(
      (p) => {
        setGeoBusy(false); follow.current = true
        setPos(p.coords.latitude, p.coords.longitude, p.coords.accuracy)
      },
      (e) => {
        setGeoBusy(false)
        onChange({ ...loc, status: e.code === e.PERMISSION_DENIED ? 'denied' : 'manual' })
        setGeoErr(e.message || 'Location unavailable')
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 },
    )
  }, [loc, onChange, setPos])

  useEffect(() => { useGps() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const recenter = () => { follow.current = true; if (loc.lat != null) useGps() }

  const search = async () => {
    if (!query.trim()) return
    setGeoBusy(true); setGeoErr('')
    const hit = await forwardGeocode(query.trim())
    setGeoBusy(false)
    if (hit) { follow.current = true; setPos(hit.lat, hit.lon, null); onChange((p: LocState) => ({ ...p, address: hit.name })) }
    else setGeoErr('No match found — try a landmark or drop the pin manually.')
  }

  const statusBadge = {
    idle: 'idle', locating: 'Locating…', locked: loc.accuracy ? `Location locked, accuracy ±${Math.round(loc.accuracy)} m` : 'Location set',
    denied: 'Permission denied, set the pin manually', manual: 'Pin set manually',
  }[loc.status]

  return (
    <div className="space-y-3">
      {/* status + controls */}
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn_badge(loc.status)}>{geoBusy && loc.status === 'locating' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Navigation className="h-3 w-3" />}{statusBadge}</span>
        <Button size="sm" variant="outline" onClick={useGps} disabled={geoBusy}><LocateFixed className="h-3.5 w-3.5" /> Use my current location</Button>
        <Button size="sm" variant="ghost" onClick={recenter}><Crosshair className="h-3.5 w-3.5" /> Recenter</Button>
      </div>

      {/* address search */}
      <div className="flex gap-2">
        <Input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), void search())}
          placeholder="Search address or landmark (Nominatim)" aria-label="Address search" />
        <Button variant="secondary" onClick={() => void search()} disabled={geoBusy}>Search</Button>
      </div>
      {geoErr && <p className="text-xs text-amber-600">{geoErr}</p>}

      {/* map */}
      <div className="relative h-72 overflow-hidden rounded-2xl border border-[var(--border)] sm:h-80">
        <MapContainer center={loc.lat != null && loc.lon != null ? [loc.lat, loc.lon] : defaultCenter} zoom={16}
          className="h-full w-full" scrollWheelZoom attributionControl>
          <TileLayer url={TILE_URL} attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' />
          {loc.lat != null && loc.lon != null && (
            <>
              {loc.accuracy != null && loc.accuracy < 5000 && (
                <AccuracyCircle center={[loc.lat, loc.lon]} radius={loc.accuracy} />
              )}
              <Marker position={[loc.lat, loc.lon]} icon={pinIcon} draggable
                eventHandlers={{ dragend: (e) => {
                  const m = (e.target as L.Marker).getLatLng()
                  setPos(m.lat, m.lng, null)
                } }} />
            </>
          )}
          <MapController loc={loc} onPick={(lat, lon) => { follow.current = false; setPos(lat, lon, null) }} follow={follow} />
        </MapContainer>
        {!loc.lat && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-[var(--surface)]/60 text-sm text-[var(--text-muted)]">
            Click the map or use GPS to set the complaint location
          </div>
        )}
      </div>
      <p className="text-[11px] text-[var(--text-faint)]">Map data © OpenStreetMap contributors · Geocoding © Nominatim</p>
    </div>
  )
}

function cn_badge(status: LocState['status']) {
  const tones: Record<string, string> = {
    locating: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
    locked: 'bg-brand-100 text-brand-700 dark:bg-brand-900/40 dark:text-brand-300',
    denied: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
    manual: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
    idle: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300',
  }
  return `inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${tones[status]}`
}

function AccuracyCircle({ center, radius }: { center: [number, number]; radius: number }) {
  const map = useMap()
  const ref = useRef<L.Circle | null>(null)
  useEffect(() => {
    ref.current = L.circle(center, { radius, color: '#059669', weight: 1, fillOpacity: 0.08 })
      .addTo(map)
    return () => { ref.current?.remove() }
  }, [center[0], center[1], radius, map])
  return null
}
