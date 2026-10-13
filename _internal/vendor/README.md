# _internal/vendor · 本地化的前端依赖

页面**不引用任何 CDN**，这四个依赖全部放在这里，由 `server.py` 的静态目录按相对路径发给浏览器
（`TagSDanbooru.html` 里写的是 `_internal/vendor/...`）。这样断网、代理抖动、CDN 被挡都不会影响界面。

> 为什么非本地化不可：之前样式表在 `cdn.tailwindcss.com`、图标字体等在 `cdnjs.cloudflare.com`。
> 本机系统代理是 `127.0.0.1:6696`，而代理排除列表里有 `127.*` —— 本地页面永远通、CDN 却要走代理，
> 于是代理一抖，**四个外链同时挂**，页面就只剩内联 `<style>` 那点背景，退化成"裸 HTML"。

| 文件 | 版本 | 来源 |
| --- | --- | --- |
| `tailwindcss-3.4.17.js` | 3.4.17 | `https://cdn.tailwindcss.com/3.4.17`（单文件浏览器端 JIT，行为与 Play CDN 完全一致） |
| `papaparse-5.4.1.min.js` | 5.4.1 | `https://cdnjs.cloudflare.com/ajax/libs/PapaParse/5.4.1/papaparse.min.js` |
| `sortable-1.15.2.min.js` | 1.15.2 | `https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.15.2/Sortable.min.js` |
| `fontawesome/css/all.min.css` + `fontawesome/webfonts/*.woff2` | 6.5.2 | `https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/…` |

许可证：Tailwind CSS（MIT）、PapaParse（MIT）、Sortable（MIT）、Font Awesome Free（图标 CC BY 4.0 / 字体 SIL OFL 1.1 / 代码 MIT）。

## 怎么更新

```powershell
# 以 tailwind 为例，改版本号后重新下载，然后改 TagSDanbooru.html 里的文件名
Invoke-WebRequest 'https://cdn.tailwindcss.com/3.4.17' -OutFile '_internal/vendor/tailwindcss-3.4.17.js'
```

Font Awesome 只取了 `all.min.css` 依赖的 4 个 `.woff2`（`fa-solid-900` / `fa-regular-400` / `fa-brands-400` /
`fa-v4compatibility`）；同一个 `@font-face` 里的 `.ttf` 是老浏览器兜底，现代浏览器会走 `woff2`，不需要一起下。

**注意**：这些文件必须保持原样（不要手动格式化或改行尾）。`.gitattributes` 里把字体标成了 `binary`，
并把整个 `_internal/vendor/**` 设成 `-text`（不做任何行尾转换），这样仓库里的字节和上游一致，可以直接按哈希比对。
另外 `server.py` 的静态中间件会为 `.woff2` 补上 `font/woff2` 响应头 —— aiohttp 3.13 用的是它自己那份
MimeTypes 表，不认 `mimetypes.add_type`，少了这一步字体在 Windows 上会被发成 `application/octet-stream`。

## 页面侧的自检

`TagSDanbooru.html` 末尾有一段纯原生 JS 的自检：如果 `window.tailwind` / `Papa` / `Sortable` 缺失、
图标字体没生效或 `#tag-list` 不再是 `grid`，页面顶部会直接弹出一条红色横幅说清楚缺什么 —— 
以后万一这里的文件被删了或没下全，不会再"静默退化"成裸页面。
