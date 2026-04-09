export default function LanguageToggle({ lang, onToggle, t }) {
  const isArabic = lang === 'ar'

  return (
    <button
      className="btn btn-outline btn-sm"
      onClick={onToggle}
      type="button"
      title={t('common.language')}
      aria-label={t('common.language')}
    >
      {isArabic ? 'EN' : 'AR'}
    </button>
  )
}
