/** Just enough of a reply to recognize it in the shade. */
export const PREVIEW_CHARS = 80;

/** Written in place of a cancelled answer, in every UI language the server can produce. */
const CANCELLED = /^\s*_\(Cancelled/i;

/**
 * The reply as one line for the notification body. Fenced code is dropped - its syntax reads as
 * noise there - and a cancelled answer has nothing worth announcing.
 */
export function replyPreview(content: string): string {
  if (!content.trim() || CANCELLED.test(content)) {
    return '';
  }
  const text = content.replace(/```[\s\S]*?```/g, ' ').replace(/\s+/g, ' ').trim();
  return text.length > PREVIEW_CHARS ? `${text.slice(0, PREVIEW_CHARS)}…` : text;
}

/** The conversation's own name, the Agent answering in it, in that order. */
export function noticeTitle(sessionTitle?: string, agentName?: string): string {
  return sessionTitle?.trim() || agentName?.trim() || 'CowAgent';
}
