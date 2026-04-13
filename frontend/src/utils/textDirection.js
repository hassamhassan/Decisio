const RTL_CHAR_REGEX = /[\u0591-\u07FF\uFB1D-\uFDFD\uFE70-\uFEFC]/
const LTR_CHAR_REGEX = /[A-Za-z]/

function flattenText(value, parts, budget) {
  if (budget.count > budget.max) return
  if (typeof value === 'string') {
    const text = value.trim()
    if (text) {
      parts.push(text)
      budget.count += text.length
    }
    return
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      flattenText(item, parts, budget)
      if (budget.count > budget.max) return
    }
    return
  }
  if (value && typeof value === 'object') {
    for (const nested of Object.values(value)) {
      flattenText(nested, parts, budget)
      if (budget.count > budget.max) return
    }
  }
}

export function resolveTextDirection(value, fallbackDir = 'ltr') {
  const parts = []
  flattenText(value, parts, { count: 0, max: 2000 })
  const sample = parts.join(' ').trim()
  if (!sample) return fallbackDir

  const hasRtl = RTL_CHAR_REGEX.test(sample)
  const hasLtr = LTR_CHAR_REGEX.test(sample)
  if (hasRtl && !hasLtr) return 'rtl'
  if (!hasRtl && hasLtr) return 'ltr'
  if (hasRtl) return 'rtl'
  return fallbackDir
}
