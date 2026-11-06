import { useTranslation } from 'react-i18next'
import {
  Button, Card, CardHeader, Input, Field, Textarea, Select, StatusChip, SeverityBadge,
  RingProgress, StatCard, Skeleton, EmptyState, Avatar, Kbd,
} from '../components/ui/primitives'
import { TrackIdSearch } from '../components/layout/TrackIdSearch'
import { FileText, Bell, CheckCircle2 } from 'lucide-react'

/** /design — living style guide for the component library. */
export function DesignPage() {
  const { t } = useTranslation()
  return (
    <div className="mx-auto max-w-5xl space-y-8 px-4 py-8">
      <h1 className="font-display text-3xl font-bold">CrowdResolve Design System</h1>

      <Card>
        <CardHeader title="Buttons" />
        <div className="flex flex-wrap gap-2">
          <Button>Primary</Button><Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button><Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button><Button variant="teal">Teal</Button>
          <Button size="sm">Small</Button><Button size="lg">Large</Button>
          <Button disabled>Disabled</Button>
        </div>
      </Card>

      <Card>
        <CardHeader title="Form controls" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Text input" hint="Helper text"><Input placeholder="Placeholder" /></Field>
          <Field label="With error" error="This field is required"><Input /></Field>
          <Field label="Textarea"><Textarea placeholder="Long text…" /></Field>
          <Field label="Select"><Select><option>A</option><option>B</option></Select></Field>
        </div>
      </Card>

      <Card>
        <CardHeader title="Badges & chips" />
        <div className="flex flex-wrap gap-2">
          {['received', 'under_review', 'in_progress', 'awaiting_verification', 'resolved', 'closed', 'reopened'].map((s) => <StatusChip key={s} status={s} />)}
          <SeverityBadge severity="low" /><SeverityBadge severity="medium" /><SeverityBadge severity="high" /><SeverityBadge severity="critical" />
          <Avatar name="Aarav Sharma" /><Kbd>⌘K</Kbd>
        </div>
      </Card>

      <Card>
        <CardHeader title="Stats & progress" />
        <div className="grid gap-4 sm:grid-cols-3">
          <StatCard label="Complaints Filed" value="1,284" delta={{ value: '+12%', positive: true }} spark={[2, 4, 3, 6, 5, 8, 12]} icon={<FileText className="h-5 w-5" />} />
          <StatCard label="Resolved" value="986" delta={{ value: '+8%', positive: true }} icon={<CheckCircle2 className="h-5 w-5" />} />
          <div className="flex items-center justify-center"><RingProgress value={87} label="SLA" /></div>
        </div>
      </Card>

      <Card>
        <CardHeader title="Track ID search (all variants)" />
        <div className="space-y-4">
          <TrackIdSearch />
          <TrackIdSearch compact />
          <TrackIdSearch large />
        </div>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card><CardHeader title="Skeleton" /><Skeleton className="h-20 w-full" /><Skeleton className="mt-2 h-6 w-2/3" /></Card>
        <Card><EmptyState title={t('table.empty')} body="Empty states explain what to do next." icon={<Bell className="h-7 w-7" />} /></Card>
      </div>

      <Card>
        <CardHeader title="Typography" />
        <p className="font-display text-3xl font-bold">Poppins Display 3xl</p>
        <p className="mt-2 text-lg font-semibold">Inter semibold body</p>
        <p className="mt-1 text-sm text-[var(--text-muted)]">Inter regular muted body text for descriptions and helper copy.</p>
      </Card>
    </div>
  )
}
