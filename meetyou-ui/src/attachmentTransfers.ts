import {
  createClientAttachmentDownloadTicket,
  downloadClientAttachmentContent,
  resolveClientAttachmentDownloadPlan,
} from './clientApi'

export async function triggerAttachmentDownload(
  baseUrl: string,
  attachmentId: string,
  clientId?: string,
): Promise<void> {
  const ticket = await createClientAttachmentDownloadTicket(baseUrl, attachmentId, clientId)
  const link = document.createElement('a')
  link.rel = 'noopener noreferrer'
  link.style.display = 'none'
  const plan = resolveClientAttachmentDownloadPlan(ticket)
  if (plan.mode === 'direct') {
    link.href = plan.url
    link.download = plan.fileName || attachmentId
    link.target = '_blank'
    link.referrerPolicy = 'no-referrer'
    document.body.appendChild(link)
    link.click()
    link.remove()
    return
  }
  const blob = await downloadClientAttachmentContent(plan.url)
  const objectUrl = URL.createObjectURL(blob)
  link.href = objectUrl
  link.download = plan.fileName || attachmentId
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
}
