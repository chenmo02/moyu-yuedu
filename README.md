<div align="center">

<img src="moyu-256.png" width="96" alt="摸鱼阅读器图标" />

# 摸鱼阅读器 · MoyuReader

**把小说阅读器放进 AI 聊天界面外观里的 Windows 本地单机工具**

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6)
![Storage](https://img.shields.io/badge/Storage-IndexedDB%20%2F%20local-6F42C1)
![Build](https://img.shields.io/badge/Build-PyInstaller-5C9E42)

</div>

---

## 这是什么

一个**完全在本机运行**的阅读器：页面外观是一份 DeepSeek 聊天页的静态快照，但侧边栏是书架与历史会话，消息区是小说正文，底部输入框刻意不联网。后端是一个用 Python 标准库写的本地 HTTP/HTTPS 服务，负责页面分发、书源代理与 TXT 查找替换。

首次运行可选择把地址栏伪装成 `https://chat.deepseek6.com/a/chat/s/<uuid>`（一次性修改 hosts 与本地证书）；不授权则自动退回 `http://127.0.0.1:8765/a/chat/s/<uuid>`，**功能完全一致**。项目不连接任何 DeepSeek 服务，不上传阅读数据，也没有账号与云同步。

> 本项目与 DeepSeek 官方无任何关联，界面外观及商标归原权利人所有；`DeepSeekUI/` 中的快照仅作为本地界面参考。

## 主要功能

**阅读**

- 拖入窗口、`Ctrl+O` 或按 `B` 导入本地纯文本（`.txt` / `.md` / `.text`，文件选择框未限制扩展名）；自动识别 UTF-8 / GBK，按中英文常见章节标题正则自动分章（第 X 章、序章、楔子、番外、Chapter N 等）。
- 目录搜索跳转、上下章切换、键盘翻页、百分比进度；阅读位置写入 IndexedDB，关闭页面或切到后台时同步落盘，下次打开自动续读。
- 排版设置：字号 13–24px、行距、段间距、首行缩进、进度显示开关。

**在线书源**

- 导入「阅读 3.x」书源 JSON，支持链接、`yuedu://` 一键导入地址与源仓库详情页，单次 1–1000 个书源；多书源并行搜书，可随时停止；目录分页自动抓取、正文分页合并、`replaceRegex` 清洗、章节内容缓存。
- 规则兼容 CSS（含 `class.` / `id.` / `tag.`、`:eq()`）、XPath、JSONPath、`||` 备选与 `##` 正则替换；**不执行书源中的 JS 规则**。
- 书源设置可批量清理停用/不兼容项，或一键清空，且不会动到书架里的书与阅读进度。

**界面伪装**

- 侧边栏保留 100 条历史会话标题与 20 段完整技术问答；可自定义会话标题、日期分组、提问、思考过程与回答，支持 ` ``` ` 代码块渲染。
- `Esc` 在阅读页与伪装首页之间切换；`Ctrl+Shift+X` 紧急隐藏为一份「会议纪要」并把标签页标题改为 `会议纪要.docx - Word`，按任意键恢复。
- 历史会话搜索、头像与昵称自定义。

**本地工具**

- TXT 查找替换：调用 Windows 原生文件选择框，按字面量匹配，逐处 / 全部替换，保留原编码与 BOM；写回前校验文件哈希并使用临时文件原子替换，避免覆盖其他程序的修改。

## 快速开始

### 环境要求

| 项 | 要求 |
| --- | --- |
| 操作系统 | Windows（`ctypes.windll`、`winreg`、`certutil`、原生文件对话框） |
| Python | 3.9 及以上（开发环境为 3.13），打包成 exe 后无需 Python |
| 浏览器 | Chrome / Edge 等支持 IndexedDB 的现代浏览器 |
| 端口 | 伪装模式需要 443 空闲；回退模式使用 8765 |

### 方式一：源码运行（推荐先试）

```bash
git clone https://github.com/chenmo02/moyu-yuedu.git
cd moyu-yuedu
python -m pip install -r requirements.txt
python app.py --local
```

`--local` 不弹 UAC、不修改任何系统设置，浏览器会自动打开本地地址。若希望伪装地址栏，直接运行 `python app.py` 并在弹窗中选「是」，程序会请求一次管理员权限完成三件事：

1. 在 hosts 中追加 `127.0.0.1  chat.deepseek6.com`；
2. 把本地自签 CA 装入「受信任的根证书颁发机构」；
3. 把该域名写入系统代理绕过列表（未启用代理则跳过）。

之后每次启动直接打开 `https://chat.deepseek6.com/a/chat/s/<uuid>`，带锁标、无证书警告。选「否」或授权失败则自动使用本地地址，可再次运行并选「是」补做配置。

`server.py` 是面向源码调试的另一个入口（可配置环境变量、支持从旧 HTTP 地址迁移书架），需先手工配置 hosts 与证书：

```bat
:: C:\Windows\System32\drivers\etc\hosts
127.0.0.1  chat.deepseek6.com

:: 安装证书（当前用户）
certutil -user -addstore -f Root cert\ca.crt
```

```bash
python server.py          # 或双击「阅读器.bat」用 pythonw 静默启动
python server.py --no-open
```

### 方式二：打包为单文件 exe

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm MoyuReader.spec
```

产物为 `dist/MoyuReader.exe`：单文件、无需 Python、无需携带其他资源，可拷贝到其他 Windows 电脑，首次运行时重复一次性配置。`dist/使用说明.txt` 是面向最终用户的简明说明；仓库中的 `打包命令.txt` 记录了同一条打包命令。

> 443 端口被占用时，`app.py` 会回退到 8765，也可用 `--port 8443` 指定；`server.py` 会自动尝试 8443。

## 快捷键

| 按键 | 作用 |
| --- | --- |
| `Esc` | 在阅读页 / 伪装首页之间切换（有弹窗时先关闭弹窗） |
| `Ctrl + Shift + X` | 紧急隐藏（会议纪要白屏），按任意键恢复 |
| `?` | 快捷键帮助 |
| `C` | 章节目录（可搜索标题） |
| `B` / `Ctrl + O` | 书架 / 导入本地小说 |
| `Space`、`PageDown`、`→`、`J` | 下一页 |
| `PageUp`、`←`、`K` | 上一页 |
| `]` / `[` | 下一章 / 上一章 |
| `Ctrl + ,` | 阅读设置 |
| `Ctrl + B` | 收起 / 展开侧边栏 |
| `Ctrl + +` / `Ctrl + -` | 字号加减 |
| `Ctrl + J` | 返回伪装首页 |

输入框聚焦时不触发翻页类快捷键（Ctrl 组合键仍生效），`Esc` 与紧急隐藏不受影响。

## 命令行与配置

`app.py`（也是 exe 的入口）参数：

| 参数 | 说明 |
| --- | --- |
| `--local` | 强制使用 `http://127.0.0.1:8765`，不做伪装配置 |
| `--port N` | 指定 HTTPS 端口（443 被占用时可用 8443） |
| `--no-open` | 只启动服务，不自动打开浏览器 |
| `--reset` | 清空本地缓存（hosts 与证书需手动删除） |
| `--setup` | 仅执行提权配置，由提权后的进程内部调用 |

`server.py` 环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DSR_DOMAIN` | `chat.deepseek6.com` | 伪装域名（更换后证书需重签） |
| `DSR_HTTPS_PORT` | `443` | HTTPS 端口 |
| `DSR_HTTP_PORT` | `80` | 旧地址明文端口，用于书架迁移 |
| `DSR_HOST` | 自动选择 | 迁移页使用的主机地址 |

## 数据存储与迁移

| 位置 | 内容 |
| --- | --- |
| `%LOCALAPPDATA%\MoyuReader\` | 会话 id、`dump.json`、`migrated.flag`、`setup.ok` |
| 浏览器 IndexedDB `dsreader` | `books` / `texts` / `sources`：书架、正文、书源 |
| 浏览器 `localStorage` | 排版设置（`dsr:` 前缀）、伪装会话编辑内容 |

换域名或换协议等于换 origin，浏览器里的书架不会自动跟过来。`server.py` 首次启动会先打开旧地址的 `/__migrate`，把 IndexedDB 与 `dsr:` 开头的 localStorage 打包 POST 到 `/__dump`，再跳转新地址恢复，成功后写入 `migrated.flag`；`app.py` 也提供同样的迁移页与恢复接口。

## 项目结构

| 文件 | 作用 |
| --- | --- |
| `app.py` | 打包入口：一次性配置、本地 HTTPS/HTTP 服务、迁移接口、命令行参数 |
| `server.py` | 源码运行入口：可配置域名/端口，含 80 端口旧地址迁移 |
| `index.html` | 单页前端：伪装 UI + 阅读器 + 书架 + 各弹窗（约 3200 行，含样式与脚本） |
| `book_sources.py` | 阅读 3.x 书源导入、规则解析与带防护的远程请求 |
| `txt_tools.py` | Windows 文件选择、编码识别与 TXT 原子写入 |
| `cert/` | 本地自签 CA、站点证书及 OpenSSL 配置 |
| `MoyuReader.spec` | PyInstaller 单文件打包配置 |
| `requirements.txt` | Python 第三方依赖（仅书源模块需要） |
| `tests/` | Node 与 Python 用例 |
| `DeepSeekUI/` | 界面参考快照，`logo/` 与 `moyu-256.png` 为图标素材 |
| `阅读器.bat`、`打包命令.txt`、`dist/使用说明.txt` | 启动、打包与最终用户说明 |

## 运行测试

```bash
node --test tests/*.cjs
python -m unittest discover -s tests -p "test_*.py"
```

Node 用例覆盖章节解析、进度保存、伪装 UI 一致性、TXT 字面量匹配、在线书源导入与清理；Python 用例覆盖书源规则解析、重定向与 SSRF 防护、TXT 编码/BOM 往返。**Python 用例需先安装 `requirements.txt`**，Node 用例无额外依赖。

## 安全与隐私边界

1. **本地优先**：页面与数据都在本机，无账号、无遥测、无云同步。除用户自行配置的书源会向第三方站点发起请求外，其余功能不需要联网。
2. **管理员权限仅用于一次性配置**：hosts、根证书存储、代理绕过列表。选「否」或使用 `--local` 即可完全跳过；卸载时需手动清理（见下节）。
3. **请勿信任仓库内的演示证书**：`cert/ca.key` 是自签 CA 的私钥，属于演示材料。公开仓库中的私钥不应被任何机器信任；正式使用请重新签发 CA 与站点证书，并把私钥移出版本库。
4. **后端接口的防护**：书源接口校验同源 Origin 与 `Sec-Fetch-Site`、限制请求体大小；目标 URL 必须为公网地址（拒绝本机/内网，防 SSRF）、逐跳校验重定向、最多 6 跳、响应上限 8 MB、连接/读取超时 8/12 秒；`@js:`、`<js>`、`{{...}}` 脚本规则一律禁用。TXT 接口校验同源、令牌与文件哈希，写回采用临时文件 + 原子替换。
5. **静态快照**：页面不会向 DeepSeek 发送任何请求，输入框的「网络连接超时」是刻意行为；地址栏的锁标仅来自本机安装的 CA。

## 已知限制

- 仅支持 Windows；Linux / macOS 无法完成提权配置与原生文件对话框。
- 书源兼容文字小说类「阅读 3.x」规则的常见子集，不支持登录、验证码、脚本规则、图片/漫画源；目录分页上限 200 页，正文分页上限 10 页。
- 书架与进度绑定「这台电脑的这个浏览器」，换设备需重新导入；伪装会话的自定义内容同样只存本机。
- 伪装 UI 是固定快照，不会随官方页面更新；自动分章依赖标题正则，格式不规范的文本可能被整体当作一章。
- 无云端同步，也不提供书源内容的合法性校验；书源站点与内容由第三方提供。

## 卸载与清理配置

1. 删除 `MoyuReader.exe` 与 `%LOCALAPPDATA%\MoyuReader` 文件夹；
2. 在 `C:\Windows\System32\drivers\etc\hosts` 中删除 `chat.deepseek6.com` 那一行；
3. `certmgr.msc` → 受信任的根证书颁发机构 → 删除 `DeepSeek Local CA`；
4. 系统代理设置 →「请勿对以下列条目开头的地址使用代理服务器」中移除 `chat.deepseek6.com` 与 `*.deepseek6.com`。

## 免责声明

本项目仅供个人在**自己的设备**上学习与阅读自有或合法授权的文本。请勿用于违反所在单位的管理规定、规避审计或误导他人，也不要在他人设备上安装。书源站点及其内容由第三方提供，使用时请遵守版权与所在地法律法规。

## License

仓库目前未附带 `LICENSE` 文件；在补充许可声明前，默认保留所有权利（All Rights Reserved）。如需以开源方式分发，请先添加 LICENSE。
