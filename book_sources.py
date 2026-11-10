"""Import and read declarative Legado 3.x book sources."""
import json
import re
import socket
from collections import deque
from ipaddress import ip_address
from urllib.parse import parse_qs, quote, urldefrag, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup, Tag
from jsonpath_ng.ext import parse as jsonpath
from lxml import etree, html
from soupsieve.util import SelectorSyntaxError


MAX_BYTES = 8 * 1024 * 1024


def http_url(url):
    if not isinstance(url, str) or urlsplit(url).scheme not in ('http', 'https'):
        raise ValueError('地址必须以 http:// 或 https:// 开头')
    parts = urlsplit(url)
    if not parts.hostname or parts.username or parts.password:
        raise ValueError('书源地址无效')
    return url


def public_url(url):
    http_url(url)
    parts = urlsplit(url)
    addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80),
                                   type=socket.SOCK_STREAM)
    if any(not ip_address(address[4][0]).is_global for address in addresses):
        raise ValueError('书源地址不能指向本机或内网')


def fetch(url, headers=None, method='GET', body=None, charset=None):
    """Bound remote requests and validate every redirect before following it."""
    with requests.Session() as session:
        session.headers.update({'User-Agent': 'Mozilla/5.0 MoyuReader/1.0'})
        session.headers.update(headers or {})
        for _ in range(6):
            public_url(url)
            with session.request(method, url, data=body, timeout=(8, 12),
                                 allow_redirects=False, stream=True) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers['Location'])
                    if response.status_code == 303 or (response.status_code in (301, 302) and method == 'POST'):
                        method, body = 'GET', None
                    continue
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError('书源返回的数据过大')
                    chunks.append(chunk)
                raw = b''.join(chunks)
                encoding = charset
                if not encoding:
                    match = re.search(r'charset=["\s]*([\w-]+)', response.headers.get('Content-Type', ''), re.I)
                    if not match:
                        match = re.search(br'charset=["\s]*([\w-]+)', raw[:4096], re.I)
                    if match:
                        encoding = match[1]
                        if isinstance(encoding, bytes):
                            encoding = encoding.decode('ascii')
                try:
                    return raw.decode(encoding or 'utf-8-sig'), url
                except UnicodeDecodeError:
                    return raw.decode('gb18030'), url
        raise ValueError('书源重定向次数过多')


def unsupported(rule):
    return isinstance(rule, str) and bool(re.search(r'@js:|<js>|\{\{(?!\s*(?:key|page)\s*\}\})', rule, re.I))


def normalize_source(source):
    if not isinstance(source, dict):
        raise ValueError('书源必须是 JSON 对象')
    http_url(source.get('bookSourceUrl', ''))
    if not isinstance(source.get('bookSourceName'), str) or not source['bookSourceName'].strip():
        raise ValueError('书源缺少名称 bookSourceName')
    source = dict(source)
    reason = ''
    if source.get('bookSourceType', 0) not in (0, '0'):
        reason = '仅支持文字小说书源'
    required = [(source, 'searchUrl'), (source.get('ruleSearch'), 'bookList'),
                (source.get('ruleSearch'), 'name'), (source.get('ruleSearch'), 'bookUrl'),
                (source.get('ruleToc'), 'chapterList'), (source.get('ruleToc'), 'chapterName'),
                (source.get('ruleToc'), 'chapterUrl'), (source.get('ruleContent'), 'content')]
    for rules, field in required:
        if not isinstance(rules, dict) or not isinstance(rules.get(field), str) or not rules[field].strip():
            reason = reason or ('缺少阅读 3.x 规则：' + field)
        elif unsupported(rules[field]):
            reason = reason or '核心规则依赖脚本，暂不支持此书源'
    for group, field in [('ruleBookInfo', 'tocUrl'), ('ruleToc', 'nextTocUrl'),
                         ('ruleContent', 'nextContentUrl'), ('ruleContent', 'replaceRegex')]:
        rules = source.get(group)
        if isinstance(rules, dict) and unsupported(rules.get(field)):
            reason = reason or '目录或正文依赖脚本，暂不支持此书源'
    if source.get('header') and unsupported(source['header']):
        reason = reason or '请求头依赖脚本，暂不支持此书源'
    source['id'] = source['bookSourceUrl']
    source['unsupportedReason'] = reason
    source['enabled'] = source.get('enabled', True) is not False and not reason
    return source


def import_sources(address):
    address = address.strip()
    if address.startswith('yuedu://'):
        address = parse_qs(urlsplit(address).query).get('src', [''])[0]
    text, final_url = fetch(address)
    if text.lstrip().startswith('<'):
        document = BeautifulSoup(text, 'html.parser')
        link = document.select_one('input#jsonurl')
        if not link or not link.get('value'):
            raise ValueError('此地址不是书源 JSON。请打开具体书源，复制「书源地址」或「下载 JSON」链接')
        text, _ = fetch(urljoin(final_url, link['value']))
    try:
        value = json.loads(text.lstrip('\ufeff'))
    except ValueError as exc:
        raise ValueError('地址返回的不是有效的书源 JSON') from exc
    values = value if isinstance(value, list) else [value]
    if not values or len(values) > 1000:
        raise ValueError('每次请导入 1–1000 个书源')
    sources, errors = {}, []
    for item in values:
        try:
            source = normalize_source(item)
            sources[source['id']] = source
        except ValueError as exc:
            errors.append(str(exc))
    if not sources:
        raise ValueError('没有有效书源：' + '；'.join(errors[:3]))
    return {'sources': list(sources.values()), 'skipped': len(errors)}


def document(text):
    try:
        return json.loads(text)
    except ValueError:
        return BeautifulSoup(text, 'html.parser')


def select(context, selector):
    selector = selector.removeprefix('@css:').strip()
    if not selector:
        return [context]
    if selector.startswith('@json:') or selector.startswith('$'):
        expression = selector.removeprefix('@json:')
        return [match.value for match in jsonpath(expression).find(context)]
    if selector.startswith(('/', '@xpath:')):
        root = html.fromstring(str(context)) if isinstance(context, (BeautifulSoup, Tag)) else context
        return root.xpath(selector.removeprefix('@xpath:'))
    if not isinstance(context, (BeautifulSoup, Tag)):
        if isinstance(context, dict) and selector in context:
            return [context[selector]]
        return []
    # Each @ step operates on the previous step's nodes, including its indexes.
    steps = re.split(r'@(?![^\[\]]*\])(?![^()]*\))', selector)
    if len(steps) > 1:
        nodes = [context]
        for step in steps:
            nodes = [child for node in nodes for child in select(node, step)]
        return nodes
    if selector.startswith('text.'):
        text = selector[5:]
        return context.find_all(lambda node: text in ''.join(node.find_all(string=True, recursive=False)))
    selector = re.sub(r'(?<![\w-])(class|id|tag)\.([\w-]+)',
                      lambda m: {'class': '.', 'id': '#', 'tag': ''}[m[1]] + m[2], selector)
    selector = re.sub(r'\[([\w-]+)([*^$|~]?=)([^\]"\'\s]+)\]', r'[\1\2"\3"]', selector)
    selector = re.sub(r':eq\((-?\d+)\)', lambda m: ':nth-of-type(%d)' % (int(m[1]) + 1)
                      if int(m[1]) >= 0 else ':last-of-type', selector)
    index = re.search(r'(?<!\])\.(-?\d+(?::-?\d+)*)$', selector)
    if index:
        nodes = context.select(selector[:index.start()])
        return [nodes[position] for position in map(int, index[1].split(':'))
                if -len(nodes) <= position < len(nodes)]
    return context.select(selector)


def node_text(node, attribute='text'):
    if isinstance(node, (BeautifulSoup, Tag)):
        if attribute in ('text', 'html', 'textNodes'):
            node = BeautifulSoup(str(node), 'html.parser')
            for unwanted in node.select('script,style,noscript'):
                unwanted.decompose()
            if attribute == 'textNodes':
                return '\n'.join(str(child).strip() for parent in node.contents if isinstance(parent, Tag)
                                 for child in parent.children if isinstance(child, str) and child.strip())
            return node.get_text('\n', strip=True)
        value = node.get(attribute, '')
        return ' '.join(value) if isinstance(value, list) else value
    if isinstance(node, etree._Element):
        return '\n'.join(node.itertext()).strip() if attribute in ('text', 'html') else node.get(attribute, '')
    return str(node) if node is not None else ''


def rule(context, expression, many=False):
    if not expression:
        return [] if many else ''
    if unsupported(expression):
        raise ValueError('此规则依赖脚本，暂不支持')
    for option in expression.split('||'):
        parts = option.split('##')
        selector = parts[0].strip()
        if selector.startswith('+'):
            selector = selector[1:]
        reverse = selector.startswith('-')
        if reverse:
            selector = selector[1:]
        attribute = 'text'
        if selector in ('text', 'html', 'textNodes', 'href', 'src'):
            attribute, selector = selector, ''
        elif not many:
            match = re.search(r'(?<!/)@([\w-]+)$', selector)
            if match:
                attribute, selector = match[1], selector[:match.start()]
        try:
            values = select(context, selector)
        except SelectorSyntaxError as exc:
            raise ValueError('无法解析规则「%s」：%s' % (expression, str(exc).splitlines()[0])) from exc
        if reverse:
            values = values[::-1]
        if many:
            if values:
                return values
            continue
        value = '\n'.join(node_text(node, attribute) for node in values).strip()
        if len(parts) > 1:
            replacement = parts[2] if len(parts) > 2 else ''
            replacement = re.sub(r'\$(\d+)', r'\\g<\1>', replacement)
            value = re.sub(parts[1], replacement, value).strip()
        if value:
            return value
    return [] if many else ''


def optional_rule(context, expression):
    return '' if unsupported(expression) else rule(context, expression)


def request_page(source, address, key='', page=1):
    header = source.get('header') or {}
    if isinstance(header, str):
        header = json.loads(header)
    if not isinstance(header, dict):
        raise ValueError('书源请求头格式无效')
    parts = re.split(r',\s*(?=\{)', address, maxsplit=1)
    options = json.loads(parts[1]) if len(parts) > 1 else {}
    charset = options.get('charset', 'utf-8')
    address = re.sub(r'\{\{\s*key\s*\}\}', lambda _: quote(key, encoding=charset), parts[0])
    address = re.sub(r'\{\{\s*page\s*\}\}', str(page), address)
    body = options.get('body')
    if body is not None:
        if not isinstance(body, str):
            raise ValueError('暂不支持此书源的请求体格式')
        body = re.sub(r'\{\{\s*key\s*\}\}', lambda _: quote(key, encoding=charset), body)
        body = re.sub(r'\{\{\s*page\s*\}\}', str(page), body).encode(charset)
        header.setdefault('Content-Type', 'application/x-www-form-urlencoded')
    header.update(options.get('headers') or {})
    method = options.get('method', 'GET').upper()
    if method not in ('GET', 'POST'):
        raise ValueError('书源仅支持 GET / POST 请求')
    text, url = fetch(urljoin(source['bookSourceUrl'], address), header, method, body,
                      options.get('charset'))
    return document(text), url


def search(source, key, page=1):
    if not isinstance(key, str) or not key.strip() or len(key) > 100:
        raise ValueError('请输入 1–100 个字的书名或作者')
    doc, url = request_page(source, source['searchUrl'], key.strip(), page)
    rules = source['ruleSearch']
    books, seen = [], set()
    for item in rule(doc, rules['bookList'], many=True):
        name, link = rule(item, rules['name']), rule(item, rules['bookUrl'])
        if not name or not link:
            continue
        link = http_url(urljoin(url, link))
        if link in seen:
            continue
        seen.add(link)
        books.append({'name': name, 'bookUrl': link, 'author': optional_rule(item, rules.get('author')),
                      'intro': optional_rule(item, rules.get('intro'))[:500],
                      'lastChapter': optional_rule(item, rules.get('lastChapter'))})
        if len(books) >= 100:
            break
    return {'books': books}


def directory(source, book_url):
    doc, url = request_page(source, http_url(book_url))
    info = source.get('ruleBookInfo') or {}
    toc_url = rule(doc, info.get('tocUrl'))
    if toc_url:
        doc, url = request_page(source, urljoin(url, toc_url))
    rules, chapters, seen = source['ruleToc'], [], set()
    pending, scheduled = deque(), {urldefrag(url)[0]}
    while True:
        for item in rule(doc, rules['chapterList'], many=True):
            if optional_rule(item, rules.get('isVolume')).lower() in ('true', '1'):
                continue
            name, link = rule(item, rules['chapterName']), rule(item, rules['chapterUrl'])
            if name and link:
                link = http_url(urljoin(url, link))
                if link not in seen:
                    seen.add(link)
                    chapters.append({'title': name, 'url': link, 'paras': None})
        for link in rule(doc, rules.get('nextTocUrl')).splitlines():
            if not link.strip():
                continue
            next_url = urldefrag(urljoin(url, link.strip()))[0]
            if next_url not in scheduled:
                scheduled.add(next_url)
                pending.append(next_url)
        if not pending:
            break
        if len(scheduled) > 200:
            raise ValueError('目录分页超过 200 页，请换用完整目录的书源')
        doc, url = request_page(source, pending.popleft())
        scheduled.add(urldefrag(url)[0])
    if not chapters:
        raise ValueError('没有解析到章节目录，书源可能失效或需要登录')
    return {'chapters': chapters}


def chapter(source, address):
    rules, pages, visited = source['ruleContent'], [], set()
    while address not in visited:
        visited.add(address)
        doc, url = request_page(source, http_url(address))
        content = rule(doc, rules['content'])
        if rules.get('replaceRegex'):
            parts = rules['replaceRegex'].removeprefix('##').split('##')
            replacement = re.sub(r'\$(\d+)', r'\\g<\1>', parts[1] if len(parts) > 1 else '')
            content = re.sub(parts[0], replacement, content)
        if not content.strip():
            raise ValueError('没有解析到正文，书源可能失效或需要登录')
        pages.append(content)
        following = rule(doc, rules.get('nextContentUrl'))
        address = urljoin(url, following) if following else ''
        if not address or address in visited:
            break
        if len(visited) >= 10:
            raise ValueError('章节分页超过 10 页')
    return {'paras': [line.strip() for line in '\n'.join(pages).splitlines() if line.strip()]}


def handle_source_request(handler, send):
    path = urlsplit(handler.path).path
    if not path.startswith('/__sources/'):
        return False
    def respond(value, code=200):
        send(json.dumps(value, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8', code)
    origin = handler.headers.get('Origin', '')
    if (origin and urlsplit(origin).netloc != handler.headers.get('Host')) or handler.headers.get('Sec-Fetch-Site') == 'cross-site':
        respond({'error': '不允许跨站调用书源接口'}, 403)
        return True
    try:
        length = int(handler.headers.get('Content-Length') or 0)
        if length <= 0 or length > 4 * 1024 * 1024:
            respond({'error': '请求数据大小无效'}, 413)
            handler.close_connection = True
            return True
        payload = json.loads(handler.rfile.read(length).decode('utf-8'))
        if not isinstance(payload, dict):
            raise ValueError('请求格式无效')
        action = path.rsplit('/', 1)[-1]
        if action == 'import':
            result = import_sources(payload.get('url', ''))
        elif action in ('search', 'toc', 'chapter'):
            source = normalize_source(payload.get('source'))
            if source['unsupportedReason']:
                raise ValueError(source['unsupportedReason'])
            if action == 'search':
                page = int(payload.get('page', 1))
                if not 1 <= page <= 100:
                    raise ValueError('搜索页码无效')
                result = search(source, payload.get('key'), page)
            elif action == 'toc':
                result = directory(source, payload.get('bookUrl'))
            else:
                result = chapter(source, payload.get('url'))
        else:
            respond({'error': '接口不存在'}, 404)
            return True
        respond(result)
    except (ValueError, TypeError, KeyError, LookupError, re.error, etree.XPathError) as exc:
        respond({'error': str(exc) or '书源规则无效'}, 400)
    except (requests.RequestException, OSError) as exc:
        respond({'error': '无法连接书源，请检查地址、网络或更换书源（%s）' % type(exc).__name__}, 502)
    except Exception:
        respond({'error': '无法解析此书源规则，请换用 CSS、XPath 或 JSON 规则的书源'}, 400)
    return True
