import { useCallback, useMemo, useState } from 'react'
import en from './translations/en.json'
import ar from './translations/ar.json'

export const I18N_STORAGE_KEY = 'decisio_lang'
export const DEFAULT_LANG = 'en'

const RESOURCES = { en, ar }

function getNestedValue(obj, path) {
  return path.split('.').reduce((acc, key) => (acc && acc[key] !== undefined ? acc[key] : undefined), obj)
}

function interpolate(template, params = {}) {
  return String(template).replace(/\{\{(\w+)\}\}/g, (_, key) => {
    return params[key] !== undefined ? String(params[key]) : `{{${key}}}`
  })
}

function getInitialLang() {
  const stored = localStorage.getItem(I18N_STORAGE_KEY)
  return stored && RESOURCES[stored] ? stored : DEFAULT_LANG
}

export function useI18n() {
  const [lang, setLangState] = useState(getInitialLang)

  const setLang = useCallback((nextLang) => {
    const safeLang = RESOURCES[nextLang] ? nextLang : DEFAULT_LANG
    setLangState(safeLang)
    localStorage.setItem(I18N_STORAGE_KEY, safeLang)
  }, [])

  const toggleLang = useCallback(() => {
    setLang(lang === 'en' ? 'ar' : 'en')
  }, [lang, setLang])

  const t = useCallback((key, params) => {
    const current = getNestedValue(RESOURCES[lang], key)
    if (current !== undefined) {
      return typeof current === 'string' ? interpolate(current, params) : current
    }
    const fallback = getNestedValue(RESOURCES[DEFAULT_LANG], key)
    if (fallback !== undefined) {
      return typeof fallback === 'string' ? interpolate(fallback, params) : fallback
    }
    return key
  }, [lang])

  const dir = useMemo(() => (lang === 'ar' ? 'rtl' : 'ltr'), [lang])

  return { lang, dir, t, setLang, toggleLang }
}
