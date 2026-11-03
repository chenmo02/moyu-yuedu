const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

function load(names, context = {}) {
  const functions = names.map(name => {
    const match = source.match(new RegExp('  function ' + name + '\\([\\s\\S]*?\\n  \\}'));
    assert.ok(match, 'Missing function: ' + name);
    return match[0];
  });
  vm.createContext(context);
  vm.runInContext(functions.join('\n'), context);
  return context;
}

test('empty text and leading whitespace do not create empty chapters', () => {
  const { parseBook } = load(['parseBook'], {
    CH_RE: vm.runInNewContext(source.match(/var CH_RE = ([^\r\n]+);/)[1])
  });
  for (const text of ['', '\n\n', '\uFEFF \r\n\t　']) {
    assert.equal(parseBook(text).length, 0);
  }
  const chapters = parseBook('\n　\n第一章 开始\n正文\n第二章 结束\n结尾');
  assert.equal(chapters.length, 2);
  assert.equal(chapters[0].title, '第一章 开始');
  assert.equal(chapters[0].paras[0], '正文');
  assert.equal(parseBook('\n没有章节标题的正文')[0].paras[0], '没有章节标题的正文');
});

test('progress uses the actual chapter label when a preface shifts its directory index', () => {
  const progress = { textContent: '' };
  const context = load(['updateProgress'], {
    S: { total: 3, idx: 1, chapters: [{ title: '正文' }, { title: '第76章 我不出钱' }, { title: '第77章 下一章' }] },
    $: () => progress,
    percentOf: () => 0.047
  });
  context.updateProgress();
  assert.match(progress.textContent, /^第76章/);
  assert.ok(progress.textContent.includes('共3章'));
  assert.ok(progress.textContent.endsWith('4.7%'));
  context.S.chapters[1].title = '序章';
  context.updateProgress();
  assert.match(progress.textContent, /^序章/);
});

function readingContext() {
  const pending = new Map();
  const writes = [];
  let timerId = 0;
  const node = { textContent: '', classList: { remove() {}, toggle() {} } };
  const context = load(['percentOf', 'offsetInChapter', 'saveProgress', 'setMode'], {
    S: {
      total: 3, idx: 0, winStart: 0, winEnd: 1, offsets: [46, 2200],
      mode: 'read', canned: false, savedScroll: 0
    },
    CURRENT: { id: 'current', scroll: 0 },
    chatScroll: { scrollTop: 1046, clientHeight: 574, scrollHeight: 4400 },
    saveTimer: null,
    document: { body: { dataset: {} } },
    $: () => node,
    syncComposer() {}, renderFakeGroups() {}, refreshOffsets() {},
    updateActive() {}, updateProgress() {},
    clamp: (v, a, b) => Math.min(b, Math.max(a, v)),
    metaOf: record => ({ ...record }),
    dbPut: (store, record) => writes.push({ ...record }),
    ST_BOOKS: 'books',
    setTimeout: fn => { pending.set(++timerId, fn); return timerId; },
    clearTimeout: id => pending.delete(id)
  });
  return { context, writes, pending };
}

test('switching to home preserves progress and cancels a pending save', () => {
  const { context, writes, pending } = readingContext();
  context.saveProgress();
  context.setMode('home');
  assert.equal(context.S.savedScroll, 1046);
  assert.equal(context.chatScroll.scrollTop, 0);
  context.saveProgress(true);
  for (const callback of pending.values()) callback();
  assert.equal(context.CURRENT.scroll, 1000);
  assert.equal(writes.at(-1).scroll, 1000);
});

test('canned conversations cannot overwrite book progress', () => {
  const { context, writes } = readingContext();
  context.CURRENT.scroll = 1000;
  context.S.canned = true;
  context.chatScroll.scrollTop = 0;
  context.saveProgress(true);
  assert.equal(writes.length, 0);
  assert.equal(context.CURRENT.scroll, 1000);
});

test('the last chapter advances and reaches 100% at the bottom', () => {
  const { context } = readingContext();
  Object.assign(context.S, { idx: 2, winStart: 1, winEnd: 2 });
  context.chatScroll.scrollTop = 2800;
  const middle = context.percentOf();
  assert.ok(middle > 2 / 3 && middle < 1);
  context.chatScroll.scrollTop = 3826;
  assert.equal(context.percentOf(), 1);
  context.S.idx = 1;
  assert.equal(context.percentOf(), 1, 'a short final chapter can be fully visible');
  context.S.winEnd = 1;
  assert.ok(context.percentOf() < 1, 'the end of a loaded window is not the end of the book');
});

test('deleting the current book cancels pending saves before opening a replacement', () => {
  const { context, writes, pending } = readingContext();
  const remaining = { id: 'remaining' };
  context.S.books = [context.CURRENT, remaining];
  context.S.bookId = 'current';
  const deleted = [];
  let onClick;
  context.shelfList = { addEventListener: (name, fn) => { onClick = fn; } };
  context.ST_TEXT = 'texts';
  context.dbDel = (store, id) => deleted.push([store, id]);
  context.toast = context.renderShelf = () => {};
  context.openBook = id => {
    assert.equal(id, 'remaining');
    assert.equal(context.CURRENT, null);
    assert.equal(pending.size, 0);
  };
  context.saveProgress();
  vm.runInContext(source.match(/  shelfList.addEventListener\('click', function\(e\)\{[\s\S]*?\n  \}\);/)[0], context);
  const button = { dataset: { del: 'current' }, classList: { contains: () => true } };
  onClick({ target: { closest: () => button }, stopPropagation() {} });
  assert.deepEqual(deleted, [['books', 'current'], ['texts', 'current']]);
  assert.equal(context.S.books.length, 1);
  assert.equal(writes.length, 0);
});
