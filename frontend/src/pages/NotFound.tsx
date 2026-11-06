import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Button, Card } from '../components/ui/primitives'

export function NotFound() {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4">
      <Card className="max-w-md p-10 text-center">
        <p className="font-display text-6xl font-extrabold text-brand-600">404</p>
        <h1 className="font-display mt-2 text-xl font-bold text-[var(--text)]">{t('errors.notFound')}</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">{t('errors.notFoundBody')}</p>
        <Link to="/"><Button className="mt-5">{t('errors.goHome')}</Button></Link>
      </Card>
    </div>
  )
}
