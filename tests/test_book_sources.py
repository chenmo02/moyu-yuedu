from copy import deepcopy
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import book_sources as sources


SOURCE = {
    'bookSourceName': '测试书源', 'bookSourceUrl': 'https://novels.example',
    'searchUrl': '/search?q={{key}}&page={{page}}',
    'ruleSearch': {'bookList': '.book', 'name': 'a@text', 'bookUrl': 'a@href',
                   'author': '.author@text##^作者：'},
    'ruleBookInfo': {'tocUrl': '#directory@href'},
    'ruleToc': {'chapterList': '.chapter', 'chapterName': 'text', 'chapterUrl': 'href',
                'nextTocUrl': '.next@href'},
    'ruleContent': {'content': '#content@html', 'replaceRegex': '##广告', 'nextContentUrl': '.next-page@href'},
}
PAGES = {
    'https://novels.example/source.json': json.dumps(SOURCE),
    'https://novels.example/detail': '<input id="jsonurl" value="/source.json">',
    'https://novels.example/search?q=%E5%A4%9C%E8%BD%A6&page=1': '<div class="book"><a href="/book/1">夜车</a><span class="author">作者：测试</span></div><div class="book"><a href="/book/1">重复</a></div>',
    'https://novels.example/book/1': '<a id="directory" href="/toc/1">目录</a>',
    'https://novels.example/toc/1': '<a class="chapter" href="/chapter/1">第一章 夜车</a><a class="next" href="/toc/2">下一页</a>',
    'https://novels.example/toc/2': '<a class="chapter" href="/chapter/1">重复</a><a class="chapter" href="/chapter/2">第二章 到站</a><a class="next" href="/toc/1">循环页</a>',
    'https://novels.example/chapter/1': '<div id="content">段落一<br>段落二<script>恶意代码</script><p>广告</p></div><a class="next-page" href="/chapter/1-2">下一页</a>',
    'https://novels.example/chapter/1-2': '<div id="content"><p>段落三</p></div>',
    'https://novels.example/chapter/2': '<div id="content"><p>故事结束</p></div>',
}


def fixture_fetch(url, *args, **kwargs):
    return PAGES[url], url


class SourceTests(unittest.TestCase):
    def test_import_search_directory_and_multipage_content(self):
        with patch.object(sources, 'fetch', side_effect=fixture_fetch):
            for address in ['https://novels.example/source.json', 'https://novels.example/detail',
                            'yuedu://booksource/importonline?src=https%3A%2F%2Fnovels.example%2Fsource.json']:
                source = sources.import_sources(address)['sources'][0]
                self.assertTrue(source['enabled'])
            books = sources.search(source, '夜车')['books']
            self.assertEqual(len(books), 1)
            self.assertEqual(books[0]['author'], '测试')
            chapters = sources.directory(source, books[0]['bookUrl'])['chapters']
            self.assertEqual([ch['title'] for ch in chapters], ['第一章 夜车', '第二章 到站'])
            self.assertEqual(sources.chapter(source, chapters[0]['url'])['paras'], ['段落一', '段落二', '段落三'])

    def test_json_and_xpath_rules(self):
        doc = sources.document('{"data":[{"name":"夜车","url":"/1"},{"name":"远山","url":"/2"}]}')
        rows = sources.rule(doc, '$.data[*]', many=True)
        self.assertEqual([sources.rule(row, '$.name') for row in rows], ['夜车', '远山'])
        doc = sources.document('<div><a href="/book">夜车</a></div>')
        self.assertEqual(sources.rule(doc, '//a/@href'), '/book')
        self.assertEqual(sources.rule(doc, '@xpath://a/text()'), '夜车')
        self.assertEqual(sources.rule(doc, '@css:a@href'), '/book')

    def test_css_fallback_indexes_and_literal_html(self):
        doc = sources.document('<div class="items"><a href="/1">甲</a><a href="/2">乙</a></div>')
        self.assertEqual(sources.rule(doc, '#missing@text||class.items@tag.a.1@text'), '乙')
        self.assertEqual(sources.rule(doc, 'a[href*=/2]@href'), '/2')
        self.assertEqual(sources.rule(doc, 'a:eq(1)@text'), '乙')

    def test_legado_chained_rules_keep_the_last_tag_and_each_steps_index(self):
        doc = sources.document('<ul class="p2"><li><a href="/1">甲</a><a href="/extra">附录</a></li><li><a href="/2">乙</a></li></ul>')
        links = sources.rule(doc, 'ul[class="p2"]@li@a', many=True)
        self.assertEqual([sources.rule(link, 'href') for link in links], ['/1', '/extra', '/2'])
        self.assertEqual(sources.rule(doc, 'ul.p2@li.1@a@href'), '/2')
        self.assertEqual(sources.rule(doc, 'ul.p2@li.0@a.1@text'), '附录')
        self.assertEqual(sources.rule(doc, 'class.p2@tag.li.1@tag.a@text'), '乙')
        self.assertEqual(sources.rule(doc, 'ul.p2@li.0:1@a@href'), '/1\n/extra\n/2')

    def test_next_content_text_rule_and_at_sign_inside_attribute(self):
        doc = sources.document('<a href="/next" title="a@b">下一页</a><a href="/chapter">下一章</a>')
        self.assertEqual(sources.rule(doc, 'text.下一页@href'), '/next')
        self.assertEqual(sources.rule(doc, 'a[title="a@b"]@href'), '/next')

    def test_directory_collects_all_option_pages_and_deduplicates_fragments(self):
        source = deepcopy(SOURCE)
        source['ruleToc']['chapterList'] = 'ul.p2@li@a'
        source['ruleToc']['nextTocUrl'] = 'option@value'
        select = '<select><option value="/toc/1#all">1</option><option value="/toc/2#all">2</option><option value="/toc/3#all">3</option></select>'
        pages = dict(PAGES)
        for number in range(1, 4):
            pages[f'https://novels.example/toc/{number}'] = f'<ul class="p2"><li><a href="/chapter/{number}">第{number}章</a></li></ul>' + select
        with patch.object(sources, 'fetch', side_effect=lambda url, *args: (pages[url], url)) as fetch:
            chapters = sources.directory(source, 'https://novels.example/book/1')['chapters']
        self.assertEqual([chapter['title'] for chapter in chapters], ['第1章', '第2章', '第3章'])
        self.assertEqual(fetch.call_count, 4)

    def test_invalid_css_error_includes_the_failed_rule(self):
        with self.assertRaisesRegex(ValueError, 'ul@li:unknown'):
            sources.rule(sources.document('<ul><li>甲</li></ul>'), 'ul@li:unknown', many=True)

    def test_post_search_and_charset_encode_the_keyword_once(self):
        source = deepcopy(SOURCE)
        source['searchUrl'] = '/search,{"method":"POST","charset":"gbk","body":"q={{key}}&page={{page}}"}'
        with patch.object(sources, 'fetch', return_value=('<div></div>', 'https://novels.example/search')) as fetch:
            sources.search(source, '夜车')
        self.assertEqual(fetch.call_args.args[2:4], ('POST', b'q=%D2%B9%B3%B5&page=1'))
        self.assertEqual(fetch.call_args.args[4], 'gbk')

    def test_import_collection_deduplicates_skips_invalid_and_marks_scripts(self):
        scripted = deepcopy(SOURCE)
        scripted['bookSourceUrl'] = 'https://scripts.example'
        scripted['searchUrl'] = '@js:java.ajax(key)'
        value = json.dumps([SOURCE, SOURCE, scripted, {'bad': True}])
        with patch.object(sources, 'fetch', return_value=(value, 'https://novels.example/sources.json')):
            result = sources.import_sources('https://novels.example/sources.json')
        self.assertEqual(len(result['sources']), 2)
        self.assertEqual(result['skipped'], 1)
        self.assertFalse(result['sources'][1]['enabled'])
        self.assertIn('脚本', result['sources'][1]['unsupportedReason'])

    def test_invalid_import_and_missing_content_have_useful_errors(self):
        for text in ['<h1>书源列表</h1>', 'not json', '[]']:
            with patch.object(sources, 'fetch', return_value=(text, 'https://novels.example')):
                with self.assertRaises(ValueError):
                    sources.import_sources('https://novels.example')
        with patch.object(sources, 'fetch', return_value=('<html>登录</html>', 'https://novels.example')):
            with self.assertRaisesRegex(ValueError, '正文'):
                sources.chapter(SOURCE, 'https://novels.example/chapter/1')

    def test_private_urls_and_redirects_are_rejected(self):
        for address in ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1']:
            with patch.object(sources.socket, 'getaddrinfo', return_value=[(None, None, None, None, (address, 80))]):
                with self.assertRaisesRegex(ValueError, '内网'):
                    sources.public_url('http://example.com')
        for address in ['file:///C:/secrets.txt', 'http://user:password@example.com', 'javascript:alert(1)']:
            with self.assertRaises(ValueError):
                sources.http_url(address)

    def test_api_rejects_cross_origin_and_oversized_bodies(self):
        for origin, length, expected in [('https://other.example', 2, 403), ('http://localhost:8765', 5000000, 413)]:
            headers = Message()
            headers['Origin'], headers['Host'], headers['Content-Length'] = origin, 'localhost:8765', str(length)
            request = type('Request', (), {'path': '/__sources/import', 'headers': headers, 'rfile': BytesIO(b'{}')})()
            responses = []
            with patch.object(sources, 'fetch') as fetch:
                self.assertTrue(sources.handle_source_request(request, lambda *args: responses.append(args)))
                fetch.assert_not_called()
            self.assertEqual(responses[0][2], expected)

    def test_both_launchers_expose_the_same_source_api(self):
        import app
        import server
        for handler in [app.Handler, server.Handler]:
            body = json.dumps({'url': 'https://novels.example/source.json'}).encode()
            request = object.__new__(handler)
            request.path = '/__sources/import'
            request.headers = Message()
            request.headers['Host'] = 'localhost:8765'
            request.headers['Content-Length'] = str(len(body))
            request.rfile = BytesIO(body)
            responses = []
            request._send = request._send_bytes = lambda *args: responses.append(args)
            with patch.object(sources, 'fetch', side_effect=fixture_fetch):
                request.do_POST()
            self.assertEqual(json.loads(responses[0][0])['sources'][0]['bookSourceName'], '测试书源')


if __name__ == '__main__':
    unittest.main()
