const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const page = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const reference = fs.readFileSync(path.join(root, 'DeepSeekUI', 'DeepSeek参考UI.html'), 'utf8');
const disguise = page;

test('all 100 history titles retain their original order and stay local', () => {
  const expected = [...reference.matchAll(/class=c08e6e93>([^<]*)<\/div>/g)].map(match => match[1]);
  const links = [...disguise.matchAll(/<a\b[^>]*class="[^"]*history-item[^"]*"[^>]*>/g)].map(match => match[0]);
  assert.equal(expected.length, 100);
  assert.deepEqual(links.map(link => link.match(/data-title="([^"]*)"/)[1]), expected);
  for (const link of links) assert.match(link, /href="\/a\/chat\/s\//);
});

function textOf(html) {
  return html.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
}

test('the complete saved question, thought, and answer are preserved', () => {
  const start = reference.indexOf('<div class=ds-virtual-list-visible-items');
  const end = reference.indexOf('<div style=padding-bottom:24px>', start);
  assert.ok(start > 0 && end > start);
  const template = disguise.match(/<template id="referenceConversation">([\s\S]*?)<\/template>/)[1];
  assert.equal(textOf(template), textOf(reference.slice(start, end)));
});

test('the original reference stylesheet is reused without approximation', () => {
  const originalStyle = reference.match(/<style>([\s\S]*?)<\/style>/)[1];
  assert.ok(disguise.includes('<style>' + originalStyle + '</style>'));
});

test('all 20 existing simulated conversations remain available', () => {
  const keys = [...page.matchAll(/^    '([^']+)':\s*\{/gm)].map(match => match[1]);
  assert.equal(keys.length, 20);
  assert.ok(keys.includes('存储过程21000错误解决'));
  assert.ok(keys.includes('SQL语法错误Where修复'));
  new vm.Script(page.match(/<script>([\s\S]*?)<\/script>/)[1]);
});

test('reading and disguise share one UI while retaining chapter navigation and Esc behavior', () => {
  const reader = page;
  for (const id of ['listToday', 'listChapters', 'listFake', 'tocBtn', 'settings', 'userMenu']) {
    assert.ok(reader.includes('id="' + id + '"'), 'Missing reader control: ' + id);
  }
  assert.match(reader, /button\{font-family:inherit;border:0;background:none;/);
  for (const id of ['sidebar', 'main', 'composer', 'userMenu']) {
    assert.equal([...reader.matchAll(new RegExp('id="' + id + '"', 'g'))].length, 1, id + ' must be shared');
  }
  assert.ok(!reader.includes('<iframe'), 'both modes use the same document');
  assert.match(reader, /renderToday\(\);\s*renderWindow\(false\);/);
  assert.ok(reader.includes('toggleDisguise();'), 'Esc opens the selected conversation');
  assert.doesNotMatch(reader, /renderShelf\(\);\s*showCanned\('SQL加总人数'\)/, 'startup restores the reader');
});

test('home keeps the selected conversation highlighted', () => {
  const selected = new Set();
  const item = { dataset: { title: 'SQL加总人数' }, classList: { toggle: (name, on) => on ? selected.add(name) : selected.delete(name) } };
  const historyList = { hidden: true, querySelectorAll: () => [item] };
  const readerSidebar = { hidden: false }, title = { textContent: '' };
  const context = {
    S: { mode: 'home', canned: false }, historyList,
    DISGUISE: { selected: 'SQL加总人数' }, disguiseTitle: title => title,
    HISTORY_TITLES: ['SQL加总人数'],
    $: selector => selector === '#readerSidebar' ? readerSidebar : title
  };
  vm.createContext(context);
  vm.runInContext(page.match(/  function renderFakeGroups\(title\)\{[\s\S]*?\n  \}/)[0], context);
  context.renderFakeGroups(null);
  assert.equal(historyList.hidden, false);
  assert.equal(readerSidebar.hidden, true);
  assert.equal(selected.has('b64fb9ae'), true, 'the simulated row must retain the shared selected style');
});

function functions(names, context) {
  vm.createContext(context);
  vm.runInContext(names.map(name => page.match(new RegExp('  function ' + name + '\\([\\s\\S]*?\\n  \\}'))[0]).join('\n'), context);
  return context;
}

test('Esc opens the remembered conversation and then returns to reading', () => {
  const calls = [];
  const context = functions(['toggleDisguise'], {
    S: { canned: false, mode: 'read' }, DISGUISE: { selected: '病种统计报表API改造' },
    showCanned: key => calls.push(['conversation', key]), setMode: mode => calls.push(['mode', mode])
  });
  context.toggleDisguise();
  assert.deepEqual(calls.pop(), ['conversation', '病种统计报表API改造']);
  context.S.canned = true;
  context.toggleDisguise();
  assert.deepEqual(calls.pop(), ['mode', 'read']);
});

test('custom conversation text is displayed literally and fenced code is retained', () => {
  const context = functions(['renderDisguiseText'], {
    esc: text => String(text).replace(/[&<>]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[char])),
    codeBlock: (language, body) => '<pre data-lang="' + language + '">' + body + '</pre>'
  });
  const output = context.renderDisguiseText('<img src=x onerror=alert(1)>\n下一行\n```sql\nSELECT 1 < 2;\n```');
  assert.ok(output.includes('&lt;img'));
  assert.ok(!output.includes('<img'));
  assert.ok(output.includes('<br>下一行'));
  assert.ok(output.includes('data-lang="sql"'));
  assert.ok(output.includes('SELECT 1 &lt; 2;'));
});

test('loading saved disguise edits preserves stable keys and rejects unknown selection', () => {
  let rendered = 0;
  const context = functions(['loadDisguise', 'disguiseTitle'], {
    HISTORY_TITLES: ['SQL加总人数', '原始标题'], DISGUISE_GROUPS: [{id:'0', name:'昨天'}],
    DISGUISE: { selected: 'SQL加总人数', edits: {}, groups: {} },
    localStorage: { getItem: () => JSON.stringify({selected:'原始标题', edits:{'原始标题':{title:'自定义标题',group:'0',q:'问题',think:'',a:'回答'}},groups:{'0':'今天'}}) },
    renderDisguiseSidebar: () => rendered++
  });
  context.loadDisguise();
  assert.equal(context.DISGUISE.selected, '原始标题');
  assert.equal(context.disguiseTitle('原始标题'), '自定义标题');
  assert.equal(context.DISGUISE.groups['0'], '今天');
  assert.equal(rendered, 1);
  context.localStorage.getItem = () => JSON.stringify({selected:'unknown',edits:{'原始标题':{title:'bad'}}});
  context.loadDisguise();
  assert.equal(context.DISGUISE.selected, '原始标题');
  assert.equal(context.disguiseTitle('原始标题'), '自定义标题');
});
