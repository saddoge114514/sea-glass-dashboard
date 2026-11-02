# 立绘素材说明（site/assets/）

本目录下有两个来源的东西，别混着用：

## 1. 占位形象（本项目自绘，随项目一起走）

| 文件 | 用途 |
| --- | --- |
| `mascot.svg` | 主立绘（看板娘、两只游动的小鲸、背景那只） |
| `mascot-head.svg` | 小头像（页头 logo、状态横幅、卡片标题） |
| `favicon.svg` | 浏览器页签图标 |

这三个是我画的示意形象，**没有第三方权利问题**，可以随便改、随便换。
想要「完全不用第三方素材」的干净版本：把 `site/config.js` 里的 `assets` 改成

```js
assets: { mascot: "assets/mascot.svg", head: "assets/mascot-head.svg", deep: "assets/mascot.svg" }
```

再把 `mascot.webp` / `mascot-head.webp` 两个文件删掉即可（页面会自动回落，不会留破图）。

## 2. 鲸鱼娘同人立绘（第三方素材，默认启用）

| 文件 | 来源 | 授权 |
| --- | --- | --- |
| `mascot.webp` | chibi 版鲸鱼娘女仆立绘 | **CC BY-NC-SA 4.0** |
| `mascot-head.webp` | 同一套素材的头像裁切 | **CC BY-NC-SA 4.0** |

署名（原样保留，别删）：

> 吉祥物为 DeepSeek「鲸鱼娘」同人形象 · 角色原案 上善无形（OC「溟月」）· DeepSeek 元素二创 ZipZipPipe · 修复 QYQCAMIAO ·
> 素材仓库 [fornarwhal/deepseek-whale-girl-icon](https://github.com/fornarwhal/deepseek-whale-girl-icon) · 授权 CC BY-NC-SA 4.0

**CC BY-NC-SA 4.0 意味着**：署名必须留（`site/config.js` 的 `credit` 默认已经写好）、
不能拿来做商业用途、改写/再分发要沿用同一协议。
这段授权只覆盖这两张图，不影响项目其它部分的 MIT 许可。

### 没有随仓库提供的那张

原项目里还有一张「成熟比例版」的背景大立绘，作者 JerryZRic（社区投稿
[Issue #36](https://github.com/TreapGoGo/deepseek-whale-girl/issues/36)，仓库
[TreapGoGo/deepseek-whale-girl](https://github.com/TreapGoGo/deepseek-whale-girl)），
原文注明**未标注授权协议、仅作个人非商用使用**，所以没有放进本仓库。
你自己要用的话：把文件放到 `site/assets/mascot-deep.webp`，再在 `config.js` 里写

```js
assets: { mascot: "assets/mascot.webp", head: "assets/mascot-head.webp", deep: "assets/mascot-deep.webp" }
```

`.gitignore` 里已经把 `site/assets/mascot-deep.webp` 排掉了，不会误提交。

## 换形象怎么做

1. 准备好三张图（任意格式，浏览器认就行：svg / png / webp / avif）。
2. 覆盖 `site/assets/` 里同名文件，或改 `config.js` 的 `assets` 指到新文件名。
3. 图片加载失败时页面会先回落到 `mascot.svg` / `mascot-head.svg`，两张都失败才把那只藏起来——不会出现破图占位。
4. 用了别人的图，**在 `config.js` 的 `credit` 里写清作者与协议**，这是唯一不能省的一步。
