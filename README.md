---
title: zhihupost v1.5.1发布 - 支持标签 - 让你在 VS Code 中编写发布知乎文章及回答问题
title-image: ./res/media/vs-code-extension-search-zhihu-this.png
tags: Markdown 编辑器, Markdown, Visual Studio Code
url: https://zhuanlan.zhihu.com/p/2072737463072835387
---

在元数据中：
```
tags: tag1, tag 2, tag-3, 标签4
```


# zhihupost - 让你在VS Code中编写发布知乎文章及回答问题

这是一个开源项目，你可以在[keindex.zhihupost@Github](https://github.com/keindex/zhihupost)上找到它。

[![zhihu-link-card:本项目 GitHub 主页](res/media/vs-code-extension-search-zhihu.png)](https://github.com/keindex/zhihupost)

# 安装

下载release的.vsix，安装到vscode即可

## Python CLI

项目同时提供一个可安装的 Python 命令行工具，要求 Python 3.10 或更高版本：

```bash
python -m pip install -e .
zhihupost --help
```

登录时通过标准输入传入完整的知乎 Cookie header。命令会先调用只读的当前用户接口验证，验证成功后才保存凭据：

```bash
Get-Content .\cookie.txt | zhihupost login --stdin   # PowerShell
cat ./cookie.txt | zhihupost login --stdin           # macOS/Linux
```

也可以设置 `ZHIHU_COOKIE` 环境变量。它会覆盖 `login` 保存的 Cookie，适合 CI 或临时会话；程序不会把 Cookie 打印到输出中。

```bash
zhihupost whoami
zhihupost logout
```

`render` 只在本地把 Markdown 转成 HTML，`publish --dry-run` 只准备发布内容。这两个命令都不会访问知乎或 OSS，也不需要 Cookie：

```bash
zhihupost render article.md > article.html
zhihupost publish article.md --dry-run
```

通过验证后，可以发布新文章、更新已有目标，或只保存草稿：

```bash
zhihupost publish article.md
zhihupost publish article.md --draft
```

`publish-dir` 会递归处理目录下的 `.md` 文件，按相对路径排序；文件之间默认等待 60 秒，可用 `--delay` 调整：

```bash
zhihupost publish-dir ./articles --delay 60
zhihupost publish-dir ./articles --draft --delay 10
```

单独上传图片并打印知乎图片 URL：

```bash
zhihupost upload-image ./images/cover.png
```

Python CLI 使用与扩展相同的 YAML front matter。支持的字段为 `title`、`url`、`column`、`title-image` 和 `tags`；`tags` 可以写成逗号分隔的字符串，也可以写成 YAML 字符串列表：

```yaml
---
title: 我的文章
url: https://zhuanlan.zhihu.com/p/123
column: Python
title-image: ./images/cover.png
tags: Python, Markdown
# tags:
#   - Python
#   - Markdown
---
```

正文支持标题、段落、引用、列表和任务列表、表格、代码块、链接和图片、脚注、数学公式、短代码 Emoji，以及 `zhihu-link-card:` 链接卡片。相对图片路径按 Markdown 文件所在目录解析；SVG 图片不支持。

# 支持的功能


| Markdown基础功能 | 支持与否 |
| :--- | :--- |
| 章节标题 | √ *1 |
| 分割线 | √ |
| 引用 | √ |
| 链接 | √ *8 |
| 图片 | √ *6 |
| 表格 | √ *2 |
| 公式 | √ |
| 代码块 | √ |
| 加粗 | √ |
| 斜体 | √ |
| 加粗斜体嵌套 | √ |
| 删除线 | × *3 |
| 列表 | √ |
| 参考文献 | √ *4 |

| 其它特色功能 | 支持与否 |
| :--- | :--- |
| 元数据 | √ *4 |
| 目录 | × *0 |
| 章节标题自动编号 | × *0 |
| Emoji表情 | √ *5 |
| 任务列表 | √ |


| 知乎特色功能 | 支持与否 |
| --- | --- |
| 标题 | √ *7 |
| 回答问题 | √ |
| 发布文章 | √ |
| 题图 | √ *7 |
| 链接卡片 | √ *4 |
| 视频 | × |
| 好物推荐 | × |
| 附件 | × |
| 标签 | √ *7 |
| 草稿 | √|
| 赞赏 | × |
| 追更 | × |

（0）打算近期支持，star，点赞，收藏，一键三连给我动力呀

1. 最多可支持 4 级标题
2. 表格暂时不支持对齐
3. 知乎本身不支持，请大家踊跃向[知乎小管家](https://www.zhihu.com/people/zhihuadmin)提建议
4. 格式见下一小节
5. 支持大部分Emoji（很多emoji刚发的时候可以看到，但一段时间过后就会被知乎过滤掉），具体列表请查看上面的链接。
6. - 同时支持本地图片和网络链接（暂时不支持 SVG 格式）
7. 在元数据中指定
8. 不支持为图片设置连接

# Markdown 语法文档

最直接的方法是参考[上面提到的 Markdown 测试文件](https://github.com/keindex/zhihu/blob/master/WPLs-introduction-and-test.md)。

## Markdown语法
自行 Google，或查看上面的测试文件。由于本项目使用 `markdown-it` 来渲染 Markdown，所以遵循 [CommonMark](https://commonmark.org/) 规范。

## [Jekyll 元数据](https://jekyllrb.com/docs/front-matter/)
目前仅支持如下元数据：
```md
---
title: 请输入标题（若是回答的话，请删除本行）
url: 请输入知乎链接（删除本行发表新的知乎专栏文章）
column: 请输入专栏名称（若不发表到专栏，请删除本行）
title-image: 请输入专栏文章题图（若无需题图，删除本行）
tags: tag1, tag 2, tag-3, 标签4, 标签以半角逗号分隔, 只有知乎已经存在的标签才能添加成功
注意: 所有的冒号是半角冒号，冒号后面有一个半角空格
---
```

## 链接卡片
```md
[![zhihu-link-card:本项目 GitHub 主页](./pics/vs-code-extension-search-zhihu.png)](https://github.com/keindex/WPL-s)
```
语法上和一个图片链接一样，但图片的文字需要以`zhihu-link-card:`开头。

## 任务列表
```md
- [ ] 未完成的任务
- [x] 已完成的任务
    - [ ] 嵌套未完成的任务
    - [x] 嵌套已完成的任务
```

## Emoji表情
语法和 Github 中使用 Emoji 一样，自行 Google 或查看上面的测试文件。

## 参考文献
```md
   用[^n]来引用。

[^n]: https://网址.com 说明文字

注意字符 ^ 不能少。冒号后面有一个空格。网址中不能有空格。网址和说明文字之间有一个空格，说明文字自己可以有空格。
```


# 使用方法

## 登录
点击左上角![登录按钮](res/media/light/outline_login_black_24dp.png)，用知乎扫描二维码。

## 发布文章
点击右上角![发布按钮](res/media/light/outline_publish_black_24dp.png)。

## 保存草稿
点击右上角![草稿按钮](res/media/light/outline_drafts_black_24dp.png)。


# 开源协议

MIT 许可，详情请查看[LICENSE](./LICENSE)。

# 贡献
欢迎提交 issue 和 pr。

# 未来功能展望

![未来功能展望](./docs/wpls-flow.png)

# 其它信息
## 知乎文章发布的代码逻辑

![知乎文章发布的代码逻辑](./docs/wpls-flow-知乎文章发布.png)
