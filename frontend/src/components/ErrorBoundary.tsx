import { Component, type ReactNode } from 'react'
import { Button, Card } from './ui/primitives'
import { useTranslation } from 'react-i18next'

export class ErrorBoundary extends Component<{ children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null }
  static getDerivedStateFromError(err: Error) { return { err } }
  render() {
    if (this.state.err) return <BoundaryFallback error={this.state.err} reset={() => this.setState({ err: null })} />
    return this.props.children
  }
}

function BoundaryFallback({ error, reset }: { error: Error; reset: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4">
      <Card className="max-w-md p-8 text-center">
        <h1 className="font-display text-xl font-bold text-red-600">{t('errors.generic')}</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">{error.message}</p>
        <Button className="mt-4" onClick={reset}>{t('track.retry')}</Button>
      </Card>
    </div>
  )
}
