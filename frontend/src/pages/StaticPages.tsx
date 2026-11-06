import { useParams } from 'react-router-dom'
import { Card } from '../components/ui/primitives'

const PAGES: Record<string, { title: string; body: string[] }> = {
  about: { title: 'About Us', body: [
    'CrowdResolve is a civic-tech platform connecting citizens with municipal authorities.',
    'Every complaint is classified by AI, checked for duplicates, prioritized with a transparent score, and tracked until the responsible department resolves it.',
    'Our mission: make civic grievance redressal transparent, fast and accountable.',
  ] },
  faqs: { title: 'FAQs', body: [
    'Do I need an account? — No. File and track complaints with just your Complaint ID.',
    'How is priority calculated? — From severity, safety risk, report count, waiting time and infrastructure vulnerability. All factors are visible.',
    'What if it is already reported? — Similar complaints nearby are grouped; you can upvote the existing one.',
    'How do I track? — Enter your Complaint ID in the Track box on any page.',
    'What if it is not fixed? — After "resolved" you can confirm or reopen the complaint.',
  ] },
  privacy: { title: 'Privacy Policy', body: [
    'We collect only what is needed to resolve your complaint: description, optional photo, approximate location, and optional contact details.',
    'Contact details are never shown publicly. Tracking uses an unguessable ID + secret pair.',
    'Location is used solely for routing and deduplication; we never sell personal data.',
    'You may request deletion of your data via the Contact page.',
  ] },
  terms: { title: 'Terms of Use', body: [
    'By filing a complaint you confirm the information is accurate to the best of your knowledge.',
    'False or misleading reports may be flagged by the community and reviewed by moderators.',
    'CrowdResolve is not an emergency service — call 112 for emergencies.',
    'We may update these terms; continued use constitutes acceptance.',
  ] },
  accessibility: { title: 'Accessibility Statement', body: [
    'CrowdResolve aims for WCAG 2.1 AA conformance: keyboard navigation, focus rings, ARIA labels, sufficient contrast.',
    'The interface supports English and Hindi and works on mobile and desktop.',
    'If you face barriers, contact us via the Contact page.',
  ] },
  disclaimer: { title: 'Disclaimer', body: [
    'Information on this platform is provided for civic coordination. Resolution timelines are targets, not guarantees.',
    'AI classification and priority scores are assistive; final decisions rest with authorized officials.',
    'Map data © OpenStreetMap contributors. Always verify critical information.',
  ] },
  contact: { title: 'Contact Us', body: [
    'Helpline: 1800-XXX-XXXX (Mon–Sat, 9:00–18:00 IST)',
    'Email: support@crowdresolve.example',
    'Office: Civic Innovation Cell, Bhubaneswar, Odisha',
    'For emergencies call 112.',
  ] },
  'citizen-charter': { title: 'Citizen Charter', body: [
    'Right to file a complaint without login, anonymously if you wish.',
    'Right to a tracking ID and status updates.',
    'Right to confirm or dispute a resolution.',
    'Commitment: every complaint is reviewed; SLA deadlines are published per category.',
  ] },
  guidelines: { title: 'Complaint Guidelines', body: [
    'Describe what, where and how bad — one issue per complaint.',
    'Add a clear photo if possible; it speeds up triage.',
    'Do not file emergencies here — call 112.',
    'Do not file false reports; repeated false reports affect trust scoring.',
  ] },
  categories: { title: 'Categories We Handle', body: [
    'Roads — potholes, broken roads, cratered surfaces.',
    'Waste — overflowing bins, illegal dumping.',
    'Drainage — blocked drains, waterlogging.',
    'Water — leakage, supply issues.',
    'Electricity — streetlights, exposed wires, outages.',
    'Public safety — dangerous infrastructure, open manholes.',
  ] },
  timelines: { title: 'Resolution Timelines', body: [
    'Critical safety issues: target 24–72 hours.',
    'High priority: 3–7 days.',
    'Medium: 7–15 days. Low: 15–30 days.',
    'SLA deadlines depend on category and priority band and are shown on each complaint.',
  ] },
  'success-stories': { title: 'Success Stories', body: [
    '12,800+ complaints filed · 9,200+ resolved · average 4.2 days.',
    'Duplicate grouping has saved authorities thousands of redundant site visits.',
    'Ward-level resolution scores are published monthly for accountability.',
  ] },
  departments: { title: 'Departments', body: [
    'Road Maintenance, Sanitation & Waste, Drainage & Waterlogging, Water Supply, Electrical Services, Public Safety & Works.',
    'Complaints are auto-assigned by category with jurisdiction-aware routing.',
  ] },
  resources: { title: 'Resources', body: [
    'API documentation for partners and developers.',
    'Open data exports of anonymized complaint statistics.',
    'Integration guides for municipal ERP systems.',
  ] },
  'request-access': { title: 'Request Official Access', body: [
    'Government officials can request dashboard access via the Official sign-up page.',
    'An administrator verifies your department and jurisdiction before activation.',
  ] },
}

export function StaticPage() {
  const { slug } = useParams<{ slug: string }>()
  const page = PAGES[slug || ''] || { title: slug || '', body: [] }
  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <Card className="p-8">
        <h1 className="font-display text-2xl font-bold text-[var(--text)]">{page.title}</h1>
        <div className="mt-5 space-y-3">
          {page.body.map((p, i) => <p key={i} className="text-sm leading-relaxed text-[var(--text-muted)]">{p}</p>)}
        </div>
      </Card>
    </div>
  )
}
