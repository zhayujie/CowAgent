import {PREVIEW_CHARS, noticeTitle, replyPreview} from '../src/notify/preview';

it('folds a reply onto one line for the notification body', () => {
  expect(replyPreview('第一行\n\n第二行   第三行')).toBe('第一行 第二行 第三行');
});

it('drops fenced code, which reads as noise in the shade', () => {
  expect(replyPreview('结论如下：\n```\nconst a = 1;\n```\n以上')).toBe('结论如下： 以上');
});

it('cuts a long reply and marks the cut', () => {
  const preview = replyPreview('字'.repeat(PREVIEW_CHARS + 20));
  expect(preview).toHaveLength(PREVIEW_CHARS + 1);
  expect(preview.endsWith('…')).toBe(true);
});

it('announces nothing for a cancelled or empty answer', () => {
  expect(replyPreview('_(Cancelled)_')).toBe('');
  expect(replyPreview('   \n ')).toBe('');
});

it('names the conversation, then the agent, then the app', () => {
  expect(noticeTitle('周报整理', '研究员')).toBe('周报整理');
  expect(noticeTitle('', '研究员')).toBe('研究员');
  expect(noticeTitle(undefined, undefined)).toBe('CowAgent');
});
