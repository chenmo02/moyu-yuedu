const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.match(/  function literalMatches\(text, query\)\{[\s\S]*?\n  \}/)[0], context);

test('TXT search treats punctuation, dollars, and backslashes as literal text', () => {
  assert.deepEqual(Array.from(context.literalMatches('张三 $1.* \\ 张三 $1.*', '$1.*')), [3, 13]);
  assert.deepEqual(Array.from(context.literalMatches('张三 $1.* \\ 张三 $1.*', '\\')), [8]);
  assert.equal(context.literalMatches('ABC abc ABC', 'ABC').length, 2);
});

test('TXT search ignores an empty query and counts non-overlapping matches', () => {
  assert.equal(context.literalMatches('abc', '').length, 0);
  assert.deepEqual(Array.from(context.literalMatches('aaaaa', 'aa')), [0, 2]);
  assert.deepEqual(Array.from(context.literalMatches('前言\r\n张三\n张三', '张三')), [4, 7]);
});
