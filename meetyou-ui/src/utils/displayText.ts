export function normalizeAssistantDisplayText(value: string): string {
  const source = String(value || '').replace(/\r\n?/g, '\n').replace(/[ \t]+\n/g, '\n').replace(/[ \t]+$/g, '')
  if (!source) {
    return ''
  }

  const parts = source.split(/(```[\s\S]*?```)/g)
  return parts
    .map((part, index) => {
      if (index % 2 === 1) {
        return part
      }
      return part.replace(/\n{3,}/g, '\n\n')
    })
    .join('')
    .replace(/\n+$/g, '')
}
