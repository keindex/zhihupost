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