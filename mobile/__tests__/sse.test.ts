import {SSEParser, openEventStream} from '../src/api/sse';

function collect() {
  const messages: {data: string; id: string | null}[] = [];
  const parser = new SSEParser((data, id) => messages.push({data, id}));
  return {parser, messages};
}

test('parses events split across chunks', () => {
  const {parser, messages} = collect();
  parser.push('id: 1\nda');
  parser.push('ta: {"type":"delta","content":"he"}\n');
  expect(messages).toHaveLength(0);
  parser.push('\nid: 2\ndata: {"type":"done"}\n\n');
  expect(messages).toEqual([
    {data: '{"type":"delta","content":"he"}', id: '1'},
    {data: '{"type":"done"}', id: '2'},
  ]);
});

test('ignores keepalive comments and handles CRLF', () => {
  const {parser, messages} = collect();
  parser.push(': keepalive\r\n\r\ndata: a\r\ndata: b\r\n\r\n');
  expect(messages).toEqual([{data: 'a\nb', id: null}]);
});

describe('openEventStream', () => {
  class FakeXHR {
    static DONE = 4;
    static last: FakeXHR;
    responseText = '';
    readyState = 0;
    status = 0;
    aborted = false;
    onprogress: (() => void) | null = null;
    onreadystatechange: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor() {
      FakeXHR.last = this;
    }
    open() {}
    setRequestHeader() {}
    send() {}
    abort() {
      this.aborted = true;
      this.readyState = FakeXHR.DONE;
      this.onreadystatechange?.();
    }
    receive(text: string) {
      this.responseText += text;
      this.onprogress?.();
    }
  }

  const realXHR = globalThis.XMLHttpRequest;
  beforeEach(() => {
    jest.useFakeTimers();
    (globalThis as any).XMLHttpRequest = FakeXHR;
  });
  afterEach(() => {
    jest.useRealTimers();
    globalThis.XMLHttpRequest = realXHR;
  });

  const open = () => {
    const onEvent = jest.fn();
    const onClose = jest.fn();
    const handle = openEventStream({url: 'http://x/stream', headers: {}, onEvent, onClose});
    return {handle, onEvent, onClose, xhr: FakeXHR.last};
  };

  test('keepalives hold the stream open; silence closes it with an error', () => {
    const {onClose, xhr} = open();
    for (let i = 0; i < 5; i++) {
      jest.advanceTimersByTime(20_000);
      xhr.receive(': keepalive\n\n');
    }
    expect(onClose).not.toHaveBeenCalled();
    jest.advanceTimersByTime(30_000);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onClose.mock.calls[0][0]).toBeInstanceOf(Error);
    expect(xhr.aborted).toBe(true);
  });

  test('close() stops the watchdog without reporting', () => {
    const {handle, onClose} = open();
    handle.close();
    jest.advanceTimersByTime(60_000);
    expect(onClose).not.toHaveBeenCalled();
  });

  test('a throwing handler does not break later events', () => {
    const error = jest.spyOn(console, 'error').mockImplementation(() => {});
    const {onEvent, xhr} = open();
    onEvent.mockImplementationOnce(() => {
      throw new Error('boom');
    });
    xhr.receive('data: {"type":"delta"}\n\ndata: {"type":"done"}\n\n');
    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(error).toHaveBeenCalled();
    error.mockRestore();
  });
});
