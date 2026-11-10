const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

function load(names, context) {
  vm.createContext(context);
  vm.runInContext(names.map(name => {
    const match = source.match(new RegExp('  (?:async )?function ' + name + '\\([\\s\\S]*?\\n  \\}'));
    assert.ok(match, name);
    return match[0];
  }).join('\n'), context);
  return context;
}

function searchContext(count, request) {
  const nodes = {
    sourceKeyword: { value: '夜车' }, sourceSelect: { value: '' },
    sourceSearchButton: { disabled: false, textContent: '搜索小说' },
    sourceMore: { hidden: true }, sourceResults: { innerHTML: '' }
  };
  const statuses = [];
  const context = load(['sourceRequest', 'searchSources', 'stopSourceSearch', 'clearSourceSearch'], {
    SOURCES: Array.from({ length: count }, (_, i) => ({ id: String(i), bookSourceName: '书源' + i, enabled: true })),
    SOURCE_RUN: null, SOURCE_QUERY: null, SOURCE_RESULTS: [],
    $: selector => nodes[selector.slice(1)],
    sourceStatus: (...args) => statuses.push(args),
    renderSourceResults: () => { nodes.sourceResults.innerHTML = context.SOURCE_RESULTS.map(book => book.name).join(','); },
    AbortController, setTimeout, clearTimeout
  });
  if (request) context.sourceRequest = request;
  return { context, nodes, statuses };
}

const nextTurn = () => new Promise(done => setImmediate(done));
const searchResult = name => ({ books: [{ name, bookUrl: 'https://novels.example/' + name }] });

function cleanupContext(options = {}) {
  const entries = [
    { id: 'usable', enabled: true },
    { id: 'disabled', enabled: false },
    { id: 'incompatible', enabled: false, unsupportedReason: '核心规则依赖脚本' },
    { id: 'inconsistent', enabled: true, unsupportedReason: '缺少规则' }
  ];
  const manager = { disabled: false }, confirmations = [], statuses = [], transactions = [];
  const persisted = new Map(entries.map(item => [item.id, item]));
  let stops = 0, clears = 0, renders = 0;
  const context = load(['removeSourceBatch'], {
    SOURCES: entries, ST_SOURCES: 'sources', $: () => manager,
    confirm: message => { confirmations.push(message); return options.confirm !== false; },
    sourceStatus: (...args) => statuses.push(args),
    stopSourceSearch: () => stops++, clearSourceSearch: () => clears++, renderSources: () => renders++,
    dbTx: async (store, mode, update) => {
      const removed = [];
      update({ delete: id => removed.push(id) });
      transactions.push({ store, mode, removed });
      if (options.failure) return null;
      removed.forEach(id => persisted.delete(id));
      return true;
    }
  });
  return { context, manager, confirmations, statuses, transactions, persisted,
    changes: () => ({ stops, clears, renders }) };
}

test('cleanup deletes disabled or incompatible sources together while retaining usable sources', async () => {
  const ui = cleanupContext();
  await ui.context.removeSourceBatch(false);
  assert.equal(ui.confirmations.length, 1);
  assert.match(ui.confirmations[0], /3 个/);
  assert.match(ui.confirmations[0], /已停用或规则不兼容/);
  assert.deepEqual(ui.transactions, [{ store: 'sources', mode: 'readwrite', removed: ['disabled', 'incompatible', 'inconsistent'] }]);
  assert.deepEqual(Array.from(ui.context.SOURCES, item => item.id), ['usable']);
  assert.deepEqual([...ui.persisted.keys()], ['usable']);
  assert.deepEqual(ui.changes(), { stops: 1, clears: 1, renders: 1 });
  assert.match(ui.statuses.at(-1)[1], /已清理 3 个/);
  assert.equal(ui.manager.disabled, false);
});

test('clear all removes every source without touching book or chapter stores', async () => {
  const ui = cleanupContext();
  await ui.context.removeSourceBatch(true);
  assert.match(ui.confirmations[0], /全部 4 个/);
  assert.match(ui.confirmations[0], /书架中的小说和阅读进度会保留/);
  assert.equal(ui.context.SOURCES.length, 0);
  assert.equal(ui.persisted.size, 0);
  assert.equal(ui.transactions.length, 1);
  assert.equal(ui.transactions[0].store, 'sources');
  assert.equal(ui.transactions[0].removed.length, 4);
});

test('cancelling batch cleanup leaves sources and the active search unchanged', async () => {
  const ui = cleanupContext({ confirm: false });
  await ui.context.removeSourceBatch(true);
  assert.equal(ui.transactions.length, 0);
  assert.equal(ui.context.SOURCES.length, 4);
  assert.deepEqual(ui.changes(), { stops: 0, clears: 0, renders: 0 });
});

test('failed batch transaction keeps the source list and permits retry', async () => {
  const ui = cleanupContext({ failure: true });
  await ui.context.removeSourceBatch(false);
  assert.equal(ui.context.SOURCES.length, 4);
  assert.equal(ui.persisted.size, 4);
  assert.equal(ui.manager.disabled, false);
  assert.equal(ui.statuses.at(-1)[2], true);
  assert.match(ui.statuses.at(-1)[1], /失败/);
  assert.equal(ui.changes().renders, 0);
});

test('cleanup skips empty candidates and cannot run during another source change', async () => {
  const ui = cleanupContext();
  ui.context.SOURCES = [{ id: 'usable', enabled: true }];
  await ui.context.removeSourceBatch(false);
  assert.equal(ui.confirmations.length, 0);
  assert.equal(ui.transactions.length, 0);
  assert.match(ui.statuses.at(-1)[1], /没有需要清理/);
  ui.manager.disabled = true;
  await ui.context.removeSourceBatch(true);
  assert.equal(ui.confirmations.length, 0);
  assert.equal(ui.transactions.length, 0);
});

test('stopping search aborts active requests, keeps results, and stops queued sources', async () => {
  const { context, nodes, statuses } = searchContext(8);
  const requests = [];
  let aborted = 0;
  context.fetch = (url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => {
      aborted++;
      reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
    }, { once: true });
    requests.push({ signal: options.signal, resolve: name => resolve({
      ok: true, headers: { get: () => 'application/json' }, json: async () => searchResult(name)
    }) });
  });
  const search = context.searchSources(false);
  assert.equal(requests.length, 4);
  assert.equal(nodes.sourceSearchButton.textContent, '停止搜索');
  assert.equal(nodes.sourceSearchButton.disabled, false);
  requests[0].resolve('已找到');
  await nextTurn();
  assert.equal(requests.length, 5);
  assert.equal(context.SOURCE_RESULTS.length, 1);
  context.stopSourceSearch();
  const stoppedStatus = statuses.at(-1);
  await search;
  assert.equal(aborted, 4);
  assert.ok(requests.slice(1).every(request => request.signal.aborted));
  assert.equal(requests.length, 5, 'remaining sources must never start');
  assert.equal(context.SOURCE_RUN, null);
  assert.equal(context.SOURCE_RESULTS[0].name, '已找到');
  assert.equal(nodes.sourceResults.innerHTML, '已找到');
  assert.match(stoppedStatus[1], /已停止搜索，保留 1 条结果/);
  assert.equal(statuses.at(-1), stoppedStatus);
  assert.equal(nodes.sourceSearchButton.textContent, '搜索小说');
  assert.equal(nodes.sourceMore.hidden, true);
});

test('a stopped search cannot overwrite a restarted search with late successes or failures', async () => {
  const requests = [];
  const { context, nodes, statuses } = searchContext(2, () => new Promise((resolve, reject) => requests.push({ resolve, reject })));
  const oldSearch = context.searchSources(false);
  context.stopSourceSearch();
  nodes.sourceKeyword.value = '远山';
  const newSearch = context.searchSources(false);
  const newRun = context.SOURCE_RUN, newStatus = statuses.at(-1);
  requests[0].resolve(searchResult('旧结果'));
  requests[1].reject(new Error('旧错误'));
  await oldSearch;
  assert.equal(context.SOURCE_RUN, newRun);
  assert.equal(context.SOURCE_RESULTS.length, 0);
  assert.equal(statuses.at(-1), newStatus);
  assert.equal(nodes.sourceSearchButton.textContent, '停止搜索');
  requests[2].resolve(searchResult('远山'));
  requests[3].resolve({ books: [] });
  await newSearch;
  assert.equal(context.SOURCE_RUN, null);
  assert.equal(context.SOURCE_RESULTS.length, 1);
  assert.equal(context.SOURCE_RESULTS[0].name, '远山');
  assert.equal(nodes.sourceSearchButton.textContent, '搜索小说');
  assert.equal(nodes.sourceMore.hidden, false);
});

test('clicking stop bypasses form validation even when the keyword has been cleared', () => {
  let click, prevented = false, stopped = false;
  const context = vm.createContext({
    SOURCE_RUN: {}, $: () => ({ addEventListener: (event, handler) => { click = handler; } }),
    stopSourceSearch: () => { stopped = true; }
  });
  const handler = source.match(/  \$\('#sourceSearchButton'\)\.addEventListener\('click',[^\n]+/);
  assert.ok(handler);
  vm.runInContext(handler[0], context);
  click({ preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(stopped, true);
});

test('reading progress retains the online book identity and source', () => {
  const { metaOf } = load(['metaOf'], {});
  const record = { id: 'book', name: '夜车', online: true, sourceId: 'https://source.example', sourceName: '测试书源', bookUrl: 'https://source.example/book', idx: 4, scroll: 120 };
  const saved = metaOf(record);
  for (const key of Object.keys(record)) assert.equal(saved[key], record[key]);
  assert.equal(metaOf({ id: 'txt', name: 'TXT' }).online, false);
});

test('online import saves directory and first chapter before opening the reader', async () => {
  const writes = [];
  const requests = [];
  const book = { name: '夜车', bookUrl: 'https://source.example/book', source: { id: 'source', bookSourceName: '测试书源' } };
  const context = load(['addOnlineBook', 'metaOf'], {
    DB: {}, S: { books: [] }, ST_TEXT: 'texts', ST_BOOKS: 'books',
    newId: () => 'new-book',
    sourceRequest: async (action, body) => {
      requests.push(action);
      return action === 'toc' ? { chapters: [{ title: '第一章', url: 'https://source.example/1', paras: null }] } : { paras: ['正文'] };
    },
    dbPut: async (store, record) => { writes.push([store, record]); return record.id; },
    openBookRecord: (record, online) => {
      assert.equal(writes.length, 2);
      assert.equal(record.online, true);
      assert.equal(online.chapters[0].paras[0], '正文');
      return true;
    }
  });
  assert.equal(await context.addOnlineBook(book), true);
  assert.deepEqual(requests, ['toc', 'chapter']);
  assert.deepEqual(writes.map(write => write[0]), ['texts', 'books']);
  context.S.books.push(writes[1][1]);
  context.openBook = id => { assert.equal(id, 'new-book'); return true; };
  assert.equal(await context.addOnlineBook(book), true);
  assert.equal(writes.length, 2, 'opening an existing result cannot duplicate a book');
});

test('failed first chapter never creates an empty shelf entry', async () => {
  let writes = 0;
  const context = load(['addOnlineBook'], {
    DB: {}, S: { books: [] },
    sourceRequest: async action => {
      if (action === 'toc') return { chapters: [{ url: 'https://source.example/1' }] };
      throw new Error('正文失效');
    },
    dbPut: () => writes++
  });
  await assert.rejects(context.addOnlineBook({ source: { id: 'source' } }), /正文失效/);
  assert.equal(writes, 0);
});

function addResultContext(addOnlineBook) {
  const alerts = [], statuses = [];
  const button = { dataset: { onlineBook: '0' }, disabled: false, textContent: '加入书架并阅读' };
  let click, renders = 0, closes = 0;
  const context = vm.createContext({
    SOURCE_RESULTS: [{ name: '庆余年', source: { bookSourceName: '笔趣阁biqige' } }],
    $: () => ({
      addEventListener: (event, handler) => { click = handler; },
      querySelectorAll: () => [button]
    }),
    addOnlineBook,
    sourceStatus: (...args) => statuses.push(args),
    alert: message => alerts.push(message),
    renderSourceResults: () => { renders++; button.disabled = false; },
    closeSourceDialog: () => closes++, closeShelf() {}, toast() {}
  });
  const handler = source.match(/  \$\('#sourceResults'\)\.addEventListener\('click', async function\(e\)\{[\s\S]*?\n  \}\);/);
  assert.ok(handler);
  vm.runInContext(handler[0], context);
  return { alerts, statuses, button, click: () => click({ target: { closest: () => button } }), renders: () => renders, closes: () => closes };
}

test('failed add opens an error popup with the book, source, and original error', async () => {
  const error = '无法解析此书源规则，请换用 CSS、XPath 或 JSON 规则的书源';
  const ui = addResultContext(async () => { throw new Error(error); });
  await ui.click();
  assert.equal(ui.alerts.length, 1);
  assert.ok(ui.alerts[0].includes('庆余年'));
  assert.ok(ui.alerts[0].includes('笔趣阁biqige'));
  assert.ok(ui.alerts[0].includes(error));
  assert.equal(ui.statuses.at(-1)[2], true);
  assert.equal(ui.renders(), 1);
  assert.equal(ui.button.disabled, false);
  assert.equal(ui.closes(), 0);
});

test('an existing book that cannot open also reports failure in a popup', async () => {
  const ui = addResultContext(async () => false);
  await ui.click();
  assert.equal(ui.alerts.length, 1);
  assert.match(ui.alerts[0], /打开书籍失败/);
  assert.equal(ui.button.disabled, false);
  assert.equal(ui.closes(), 0);
});

test('successful add opens the book without an error popup', async () => {
  const ui = addResultContext(async () => true);
  await ui.click();
  assert.equal(ui.alerts.length, 0);
  assert.equal(ui.closes(), 1);
  assert.equal(ui.renders(), 1);
});

test('reopening an online book uses cached content and preserves chapter progress', async () => {
  const meta = { id: 'book', online: true, idx: 1, scroll: 230 };
  const online = { source: { id: 'source' }, chapters: [{ paras: null }, { paras: ['已缓存正文'] }] };
  const context = load(['openBook'], {
    ST_BOOKS: 'books', ST_TEXT: 'texts',
    dbGet: async store => store === 'books' ? meta : { online },
    clamp: (n, min, max) => Math.max(min, Math.min(max, n)),
    sourceRequest: () => { throw new Error('cached book must work offline'); },
    openBookRecord: (record, body) => {
      assert.equal(record.idx, 1);
      assert.equal(record.scroll, 230);
      assert.equal(body, online);
      return true;
    }
  });
  assert.equal(await context.openBook('book'), true);
});

test('pending online chapter blocks unbounded loading while TXT navigation is unchanged', () => {
  let rendered = 0;
  const context = load(['appendNext'], {
    CURRENT: { online: true }, S: { total: 3, winStart: 0, winEnd: 0, chapters: [{ paras: null }, { paras: null }, { paras: null }] },
    thread: { appendChild() { rendered++; } }, chapterEl: () => ({}), refreshOffsets() {}
  });
  assert.equal(context.appendNext(), false);
  context.S.chapters[0].paras = ['已加载'];
  assert.equal(context.appendNext(), true);
  assert.equal(context.appendNext(), false);
  context.CURRENT.online = false;
  assert.equal(context.appendNext(), true);
  assert.equal(rendered, 2);
});

test('late chapter responses cannot resurrect a deleted book or replace another book', async () => {
  let resolve;
  const pending = new Promise(done => { resolve = done; });
  let writes = 0;
  const meta = { id: 'deleted', text: { source: {} } }, chapter = { url: 'https://source.example/1' };
  const body = { innerHTML: '' }, element = { querySelector: () => body, isConnected: false };
  const context = load(['loadOnlineChapter'], {
    CURRENT: null, ONLINE_PENDING: new Map(), sourceRequest: () => pending,
    indexOfBook: () => -1, dbPut: () => writes++, ST_TEXT: 'texts'
  });
  context.loadOnlineChapter(meta, chapter, element);
  resolve({ paras: ['正文'] });
  await new Promise(done => setImmediate(done));
  assert.equal(writes, 0);
  assert.equal(body.innerHTML, '<p class="online-loading">正在加载章节…</p>');
  assert.equal(context.ONLINE_PENDING.size, 0);
});
