# CrowdResolve Frontend

React 19 + TypeScript + Vite + Tailwind CSS v4. No component library dependency —
`src/components/ui/primitives.tsx` is the in-house kit (shadcn-style, copy as needed).

## Structure

```
src/
  App.tsx                  # router, role guards, lazy routes
  main.tsx                 # entry
  index.css                # Tailwind v4 theme tokens (light/dark via .dark class)
  i18n/                    # react-i18next; locales/en.json + hi.json (fallback en)
  lib/
    api.ts                 # axios client: /api base, JWT interceptor, refresh retry
    auth.tsx               # AuthProvider: admin JWT (real) + citizen local profile
    trackingId.ts          # shared complaint-ID validator/normalizer
    utils.ts               # cn(), date/time helpers
  components/
    ui/primitives.tsx      # Button Card Input Field StatusChip SeverityBadge
                           # StatCard RingProgress Skeleton EmptyState ErrorState
    layout/                # PublicLayout, AppShell (sidebar/topbar), Footer,
                           # TrackIdSearch (global), ChatWidget (⌘K palette inside AppShell)
    map/LiveLocationMap.tsx# Leaflet+OSM+Nominatim — lazy-loaded ONLY on /complaint/new
    ErrorBoundary.tsx, OfflineBanner.tsx
  pages/
    Landing.tsx            # hero + big track search + stats + roles + FAQ
    TrackResult.tsx        # /track/:id — stepper, details, polling, copy/share
    FileComplaint.tsx      # 4-step wizard: photo → AI autofill → live map → review
    auth/AuthPages.tsx     # citizen sign in/up, official sign in/up, /admin/login+TOTP
    dashboards.tsx         # citizen/official/admin dashboards, tables, detail, admin pages
    StaticPages.tsx        # privacy/terms/faqs/about/contact/etc (editable content map)
    DesignPage.tsx         # /design — component style guide
```

## Conventions

- **Terminology:** UI says "Complaint" / "File a Complaint" everywhere; internal
  field names (`public_id`, `tracking_token`, `status`) are unchanged.
- **Styling:** Tailwind utilities + `card` class; CSS vars `--surface`, `--text`,
  `--border` drive light/dark. Brand green `brand-*`, teal `teal-brand-*`.
- **Data:** TanStack Query for all server state; axios interceptors attach the
  admin JWT and retry once after `/auth/refresh` (HttpOnly cookie).
- **i18n:** every user-facing string via `t()`; add keys to `locales/en.json`
  (other locales fall back to English).
- **Forms:** react-hook-form + zod (`@hookform/resolvers`).
- **Maps:** Leaflet/react-leaflet + OSM tiles + Nominatim geocoding, lazy chunk.
  Tile URL and Nominatim base are env-configurable (`VITE_OSM_TILE_URL`,
  `VITE_NOMINATIM_URL`). Nominatim calls are debounced to ≤1 req/s and cached.

## Run

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api → :8000
npm run build      # tsc -b && vite build → dist/
```

## Backend changes still needed (tracked, not silently broken)

1. `GET /citizens/*` — citizen accounts (sign-up/login). Today citizen "session"
   is a localStorage profile + saved tracking tokens (works, but not server-side).
2. `GET /track/:publicId` — public-safe lookup by complaint ID without the secret
   (today `/complaints/track/{token}` needs the secret; UI prompts for it).
3. `GET /admin/audit-logs`, `GET/PUT /admin/settings`, `GET /admin/users`
   (approve/reject officials), departments/categories CRUD endpoints.
4. Analytics aggregates (Sankey flow, resolution trend) — UI degrades to
   computed-from-list fallbacks until dedicated endpoints exist.
5. Media serving route for resolution-proof photos (`/api/media/...` assumed).

## Roles

`super_admin|state_admin|district_admin` → Admin UI · `municipal_admin|ward_admin`
→ Official UI · everyone else → Citizen UI. Guards are client-side convenience;
the backend enforces authorization on every admin route.
