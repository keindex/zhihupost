import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { SettingEnum } from "../const/ENUM";
import { ArticlePathReg, QuestionAnswerPathReg, QuestionPathReg } from "../const/REG";
import { AnswerAPI, AnswerURL, ColumnCreateAPI, QuestionAPI, QuestionURL, ZhuanlanAPI, ZhuanlanURL } from "../const/URL";
import { PostAnswer } from "../model/publish/answer.model";
import { IColumn } from "../model/publish/column.model";
import { IProfile, ITarget } from "../model/target/target";
import { EventService } from "./event.service";
import { sendRequest } from "./http.service";
import { ProfileService } from "./profile.service";
import { WebviewService } from "./webview.service";
import { Output } from "../global/logger";
import * as MarkdownIt from "markdown-it";
import { PasteService } from "./paste.service";
import { PipeService } from "./pipe.service";

enum previewActions {
	openInBrowser = '去看看'
}

/**
 * 把元数据写回 md 文件的回调。
 * 单个文件发布时写回当前编辑器；批量发布时写回磁盘上的文件。
 */
type WriteMeta = (key: string, value: string) => void;

export class PublishService {
	public profile: IProfile;

	constructor(
		protected zhihuMdParser: MarkdownIt,
		protected defaultMdParser: MarkdownIt,
		protected webviewService: WebviewService,
		protected eventService: EventService,
		protected profileService: ProfileService,
		protected pasteService: PasteService,
		protected pipeService: PipeService
	) {
		this.registerPublishEvents();
	}

	/**
	 * When extension starts, all publish events should be re-registered,
	 * this is what pre-log tech comes in. 
	 */
	private registerPublishEvents() {
		const events = this.eventService.getEvents();
		events.forEach(e => {
			e.timeoutId = setTimeout(() => {
				this.zhihuPostNewArticle(e.content, e.title, []); // FIXME: tags
				this.eventService.destroyEvent(e.hash);
			}, e.date.getTime() - Date.now());
		})
	}

	private isZhihuArticle(meta: any): boolean {
		const url: URL|undefined = meta['url'] && new URL(meta['url']);
		if (url === undefined)
			return true;
		
		if (QuestionAnswerPathReg.test(url.pathname) || QuestionPathReg.test(url.pathname))
			return false;

		return true;
	}

	/**
	 * 渲染 markdown 文本为知乎 HTML（不依赖编辑器）。
	 *
	 * 渲染前会清空 parser 上缓存的 meta，避免上一次渲染的元数据残留
	 *（参考 https://github.com/CaliStyle/markdown-it-meta/issues/5）。
	 */
	private async renderZhihuMarkdownFromContent(text: string, baseDir?: string): Promise<string> {
		(this.zhihuMdParser as any).meta = undefined;
		const tokens = this.zhihuMdParser.parse(text, {});
		// convert local and outer link to zhihu link
		const pipePromise = this.pipeService.sanitizeMdTokens(tokens, baseDir);
		vscode.window.withProgress({
			location: vscode.ProgressLocation.Window,
			cancellable: false,
			title: '图片上传中...'
		}, (progress, token) => {
			return Promise.resolve(pipePromise);
		})
		await pipePromise;
		return this.zhihuMdParser.renderer.render(tokens, {}, {}) ;
	}

	private async renderZhihuMarkdown(textEditor: vscode.TextEditor): Promise<string> {
		const baseDir = textEditor.document.uri.scheme === "file"
			? path.dirname(textEditor.document.uri.fsPath) : undefined;
		return this.renderZhihuMarkdownFromContent(textEditor.document.getText(), baseDir);
	}

	private addMeta(textEditor: vscode.TextEditor, key: string, value: string) {
		if (!textEditor.document.lineAt(0).text.startsWith('---'))
			return;

		for (let i = 1; i < textEditor.document.lineCount; ++i) {
			const line = textEditor.document.lineAt(i);
			if (line.text.startsWith(`${key}:`)) {
				textEditor.edit(e => {
					e.replace(line.range, `${key}: ${value}`);
				})
				return;
			}

			// key does not exist, insert it
			if (line.text.startsWith('---')) {
				textEditor.edit(e => {
					e.insert(line.range.start, `${key}: ${value}\n`);
				})
				return;
			}
		}		
	}

	private insertDefaultMeta(textEditor: vscode.TextEditor) {
		// title 默认值为 Markdown 文件的第一行标题（无标题则留空）
		const firstTitle = this._getTitleFromDocument(textEditor);
		const meta_template = `---
title: ${firstTitle ? this.toYamlValue(firstTitle) : ''}
url: 
title-image: 
column: 
tags: 
---
`
		textEditor.edit(e => {
			e.insert(new vscode.Position(0, 0), meta_template);
		})
	}

	/**
	 * 写入/更新 md 文件中的元数据键值（不依赖编辑器，直接写盘）。
	 *
	 * 若文件已有 `---` 元数据块，则更新已有键或插入新键；
	 * 若没有元数据块，则在文件头部插入一个只包含该键的元数据块。
	 * 注意：这里的 `value` 会被作为 YAML 值写入，若含特殊字符请先处理。
	 */
	private writeMetaToFile(filePath: string, key: string, value: string) {
		let text: string;
		try {
			text = fs.readFileSync(filePath, 'utf8');
		} catch (error) {
			Output(`读取文件失败：${filePath}`, 'warn');
			return;
		}

		const lines = text.split(/\r?\n/);
		const eol = text.includes('\r\n') ? '\r\n' : '\n';

		// 文件以 --- 开头，说明已有元数据块
		if (lines.length > 0 && lines[0].trim() === '---') {
			let inserted = false;
			for (let i = 1; i < lines.length; i++) {
				if (lines[i].trim() === '---') {
					// 到达元数据块结尾仍未找到该键，插入
					lines.splice(i, 0, `${key}: ${value}`);
					inserted = true;
					break;
				}
				if (lines[i].startsWith(`${key}:`)) {
					lines[i] = `${key}: ${value}`;
					inserted = true;
					break;
				}
			}
			if (!inserted) {
				// 元数据块没有正常闭合，追加到文件头
				lines.splice(1, 0, `${key}: ${value}`);
			}
		} else {
			// 无元数据块：在文件头部插入
			lines.unshift('---', `${key}: ${value}`, '---');
		}

		fs.writeFileSync(filePath, lines.join(eol));
	}

	/**
	 * 判断 md 文件是否包含元数据块（--- 开头）。
	 */
	private fileHasMeta(filePath: string): boolean {
		try {
			const text = fs.readFileSync(filePath, 'utf8');
			return text.split(/\r?\n/)[0].trim() === '---';
		} catch (error) {
			return false;
		}
	}

	/**
	 * 从 md 文件内容中提取标题：
	 * 跳过元数据块和空行，取第一行正文（去掉 markdown 一级/二级标题标记）作为标题。
	 */
	private _getTitleFromContent(text: string): string | undefined {
		const lines = text.split(/\r?\n/);
		for (const line of lines) {
			const trimmed = line.trim();
			// 跳过元数据块（--- 开头）和空行
			if (trimmed === '' ) continue;
			if (trimmed.startsWith('---')) continue;
			// 去掉 markdown 一级/二级标题标记和行首空白
			const title = trimmed.replace(/^#{1,2}\s+/, '').trim();
			if (title) return title;
		}
		return undefined;
	}

	/**
	 * 从 md 文件的第一行正文中提取标题。
	 *
	 * 元数据（`---` 包裹的部分）位于文件头部，正文第一行通常是 `# 标题`，
	 * 去掉 markdown 标题标记（`#`）后即为标题。
	 */
	private _getTitleFromDocument(textEditor: vscode.TextEditor): string | undefined {
		return this._getTitleFromContent(textEditor.document.getText());
	}

	/**
	 * 将标题写为 YAML 安全的值：用双引号包裹，转义内部双引号。
	 * 避免标题含冒号、# 等字符导致 YAML 解析出错。
	 */
	private toYamlValue(value: string): string {
		return `"${value.replace(/"/g, '\\"')}"`;
	}

	private async getQuestionIdOfAnswer(url: string): Promise<string> {	
		return sendRequest({
			uri: url,
			method: 'get',
			resolveWithFullResponse: true,
			headers: {},
		}).then(resp => resp.request.href.match(/(\/question\/(\d+))?\/answer\/(\d+)$/i)[2]);
	}


	/**
	 * 返回写入元数据的回调：若调用方提供了 writeMeta 则用之，否则回退到当前编辑器。
	 */
	private _resolveWriteMeta(writeMeta?: WriteMeta): WriteMeta {
		return writeMeta || ((key: string, value: string) => {
			if (vscode.window.activeTextEditor) {
				this.addMeta(vscode.window.activeTextEditor, key, value);
			}
		});
	}

	async publish(textEditor: vscode.TextEditor, edit: vscode.TextEditorEdit, draft: boolean) {	
		const html = await this.renderZhihuMarkdown(textEditor);
		const meta = (this.zhihuMdParser as any).meta;
	
		/// Parse meta info
		if (meta === undefined) {
			vscode.window.showErrorMessage('zhihupost 使用元数据，请查看文档并添加元数据');
			this.insertDefaultMeta(textEditor);
			return;
		}

		const writeMeta = this._resolveWriteMeta();
		const titleFromDoc = this._getTitleFromDocument(textEditor);
		await this._postContent(html, meta, draft, {
			title: titleFromDoc,
			promptForTitle: true,
			writeMeta,
		});
	}

	/**
	 * 上传单个 md 文件到知乎（不依赖编辑器，直接发布新文章/更新已有文章）。
	 *
	 * 若文件没有元数据块，自动补全 `title` 为 md 文件的第一行标题（其他字段不补）。
	 * 发布成功后会把 `url` 写回文件元数据。
	 *
	 * @returns 发布成功返回 { url, title, success }，失败或跳过返回 undefined
	 */
	public async publishFile(filePath: string, draft: boolean): Promise<{ url?: string, title?: string, success?: boolean } | undefined> {
		let text: string;
		try {
			text = fs.readFileSync(filePath, 'utf8');
		} catch (error) {
			vscode.window.showErrorMessage(`读取文件失败：${filePath}`);
			return undefined;
		}

		// 去除 UTF-8 BOM，避免影响元数据块识别
		if (text.charCodeAt(0) === 0xFEFF) {
			text = text.slice(1);
		}

		// 无元数据时自动补全 title 为 md 文件的第一行标题（其他字段不补）。
		// 用 writeMetaToFile 真正写入磁盘，使文件持久化获得元数据块；
		// 这样发布成功后写回 url 时会在同一元数据块内追加，而不是另起一个块。
		if (!this.fileHasMeta(filePath)) {
			const firstTitle = this._getTitleFromContent(text);
			if (firstTitle) {
				this.writeMetaToFile(filePath, 'title', this.toYamlValue(firstTitle));
				// 内存中同步补全，用于渲染（与磁盘内容一致）
				text = `---\ntitle: ${this.toYamlValue(firstTitle)}\n---\n` + text;
			}
		}

		const baseDir = path.dirname(filePath);
		let html: string;
		try {
			html = await this.renderZhihuMarkdownFromContent(text, baseDir);
		} catch (error) {
			Output(`渲染失败：${filePath}`, 'warn');
			return undefined;
		}
		const meta = (this.zhihuMdParser as any).meta;

		// 发送前检查元数据：若无 title，
		// 则把正文（排除头部元数据块）的第一行标题写入元数据的 title 字段。
		if (meta !== undefined && meta !== null && !meta.title) {
			const firstTitle = this._getTitleFromContent(text);
			if (firstTitle) {
				this.writeMetaToFile(filePath, 'title', this.toYamlValue(firstTitle));
				// 内存中同步补全，供本次发布使用
				meta.title = firstTitle;
			}
		}

		const writeMeta: WriteMeta = (key, value) => this.writeMetaToFile(filePath, key, value);

		// 无元数据（也没有可提取的标题）→ 跳过
		if (meta === undefined || meta === null) {
			Output(`文件没有元数据且无法提取标题，跳过：${filePath}`, 'warn');
			return undefined;
		}

		const titleFromDoc = this._getTitleFromContent(text);
		return this._postContent(html, meta, draft, {
			title: titleFromDoc,
			promptForTitle: false,
			writeMeta,
		});
	}

	/**
	 * 休眠指定毫秒数（用于批量发布时控制请求间隔，避免触发知乎限流）。
	 */
	private sleep(ms: number): Promise<void> {
		return new Promise(resolve => setTimeout(resolve, ms));
	}

	/**
	 * 批量上传一个文件夹（递归）下所有 .md 文件到知乎。
	 *
	 * @param uri 文件夹路径
	 * @param draft 是否仅保存为草稿
	 */
	public async publishFolder(uri: vscode.Uri, draft: boolean) {
		const mdFiles: string[] = [];
		const walk = (dir: string) => {
			let entries: fs.Dirent[];
			try {
				entries = fs.readdirSync(dir, { withFileTypes: true });
			} catch (error) {
				return;
			}
			for (const entry of entries) {
				const full = path.join(dir, entry.name);
				if (entry.isDirectory()) {
					walk(full);
				} else if (entry.isFile() && entry.name.toLowerCase().endsWith('.md')) {
					mdFiles.push(full);
				}
			}
		};
		walk(uri.fsPath);

		if (mdFiles.length === 0) {
			vscode.window.showInformationMessage('该文件夹下没有 Markdown 文件。');
			return;
		}

		const confirm = await vscode.window.showWarningMessage(
			`将${draft ? '保存为草稿' : '发布'} ${mdFiles.length} 个 Markdown 文件到知乎，是否继续？（每篇间隔 1 分钟，预计约 ${Math.max(0, mdFiles.length - 1)} 分钟）`,
			{ modal: true },
			'确定'
		);
		if (confirm !== '确定') return;

		let success = 0;
		let skipped = 0;
		const failures: string[] = [];

		await vscode.window.withProgress({
			location: vscode.ProgressLocation.Notification,
			title: `${draft ? '保存草稿' : '发布'}中...`,
			cancellable: false,
		}, async (progress) => {
			for (let i = 0; i < mdFiles.length; i++) {
				const file = mdFiles[i];
				const rel = path.relative(uri.fsPath, file);
				progress.report({ message: `(${i + 1}/${mdFiles.length}) ${rel}` });
				try {
					const result = await this.publishFile(file, draft);
					if (result && result.success) {
						success++;
					} else {
						skipped++;
					}
				} catch (error) {
					failures.push(rel);
					Output(`发布失败：${file}，${error}`, 'warn');
				}

				// 除最后一篇外，每篇之间间隔 1 分钟，避免触发知乎限流
				if (i < mdFiles.length - 1) {
					await this.sleep(60 * 1000);
				}
			}
		});

		const msg = `完成：成功 ${success} 个，跳过 ${skipped} 个${failures.length ? `，失败 ${failures.length} 个（${failures.join('、')}）` : ''}`;
		Output(msg, 'info');
		vscode.window.showInformationMessage(msg);
	}

	/**
	 * 发布核心逻辑（编辑器与批量模式共用）。
	 *
	 * @param meta 由 markdown-it-meta 解析出的元数据
	 * @param options.title 从文档第一行提取的标题（兜底）
	 * @param options.promptForTitle 标题缺失时是否弹出输入框（编辑器模式）
	 * @param options.writeMeta 元数据写回回调
	 */
	private async _postContent(html: string, meta: any, draft: boolean, options: {
		title?: string,
		promptForTitle?: boolean,
		writeMeta?: WriteMeta,
	}): Promise<{ url?: string, title?: string, success?: boolean } | undefined> {
		const writeMeta = this._resolveWriteMeta(options.writeMeta);

		let title: string | undefined = meta.title;
		// 元数据未指定标题时，默认取 md 文件的第一行文字作为标题
		if (!title && options.title) {
			title = options.title;
		}
		if (!title && options.promptForTitle) {
			title = await this._getTitle();
			if (title) {
				writeMeta('title', title);
			} else {
				vscode.window.showErrorMessage('标题不对，中止');
				return undefined;
			}
		}
		if (!title) {
			// 批量模式下无法获取标题则跳过
			return undefined;
		}

		let titleImage: string|undefined = meta['title-image'];
		// url 为空（YAML 解析为 null）时视为未指定，发布新文章
		const url: URL|undefined = meta['url'] ? new URL(meta['url']) : undefined;
		if (titleImage !== undefined && titleImage !== null) {
			titleImage = await this.pasteService.uploadImageFromLink(titleImage);
			console.log('titleImage', titleImage);
		}
		const articleTags: string[] = meta['tags'] ? meta['tags'].split(',').map((x: string)=>x.trim()) : [];
		const column = await this._getColumnFromMeta(meta);

		/// Post article
		if (url !== undefined) { // If url is provided
			// just publish answer in terms of what shebang indicates
			if (QuestionAnswerPathReg.test(url.pathname)) {
				// Link like https://www.zhihu.com/question/481576477/answer/2085827970
				// or https://www.zhihu.com/answer/2085827970
				// answer link, update answer
				const answerId = url.pathname.replace(QuestionAnswerPathReg, '$3');
				let questionId = url.pathname.replace(QuestionAnswerPathReg, '$2');
				if (questionId === "") {
					questionId = await this.getQuestionIdOfAnswer(url.href);
				}
				console.log('questionId', questionId, 'answerId', answerId);
				const ok = await this.zhihuPostExistingAnswer(html, questionId, answerId, draft);
				return ok ? { url: url.href, title, success: true } : { url: url.href, title };
			} else if (QuestionPathReg.test(url.pathname)) {
				// Link like https://www.zhihu.com/question/481576477
				// question link, post new answer
				const questionId = url.pathname.replace(QuestionPathReg, '$1');
				const ok = await this.zhihuPostNewAnswer(html, questionId, draft, writeMeta);
				return ok ? { url: url.href, title, success: true } : { url: url.href, title };
			} else if (ArticlePathReg.test(url.pathname)) {
				// Link like https://zhuanlan.zhihu.com/p/390528313
				const articleId = url.pathname.replace(ArticlePathReg, '$1');
				const ok = await this.zhihuPostExistingArticle(html, articleId, title, articleTags, column, titleImage, draft);
				return ok ? { url: url.href, title, success: true } : { url: url.href, title };
			}
			return undefined;
		} else { // url is not provided: 没有 url 时直接发布新文章
			const ok = await this.zhihuPostNewArticle(html, title, articleTags, column, titleImage, draft, writeMeta);
			return ok ? { url: `${ZhuanlanURL}`, title, success: true } : { url: `${ZhuanlanURL}`, title };
		}
	}

	private async _getTitle(): Promise<string | undefined> {
		return vscode.window.showInputBox({
			ignoreFocusOut: true,
			prompt: "输入标题：",
			placeHolder: "",
		});
	}

	// private async _getTopics(): Promise<ITopicTarget[] | undefined> {
	// 	topics
	// 	vscode.window.showQuickPick<vscode.QuickPickItem & { value: ITopicTarget }>(
	// 		[{ label: '不发布到专栏', value: undefined }].concat(columns.map(c => ({ label: c.title, value: c }))), 
	// 		{
	// 		ignoreFocusOut: true,
		
	// 		}
	// 	).then(item => item.value);
	// }

	/**
	 * 从 md 文件的元数据 `column` 中读取目标专栏标题，并匹配出对应的专栏。
	 *
	 * 若元数据中未指定专栏（`column` 缺失或为空），则返回 undefined，
	 * 表示不发布到任何专栏。
	 */
	private async _getColumnFromMeta(meta: any): Promise<IColumn | undefined> {
		const columnTitle: string | undefined = meta && meta['column'];
		if (!columnTitle || !columnTitle.trim()) return undefined;

		const columns = await this.profileService.getColumns();
		if (columns && columns.length > 0) {
			const column = columns.find(c => c.title === columnTitle.trim());
			if (column) return column;
		}

		// 未找到专栏，尝试创建
		const created = await this._createColumn(columnTitle.trim());
		if (created) {
			return created;
		}

		vscode.window.showWarningMessage(`未找到专栏 "${columnTitle.trim()}" 且创建失败，请检查后重试。`);
		return undefined;
	}

	/**
	 * 调用知乎 API 创建新专栏。
	 */
	private async _createColumn(title: string): Promise<IColumn | undefined> {
		try {
			const resp = await sendRequest({
				uri: ColumnCreateAPI,
				method: 'post',
				body: {
					title: title,
					intro: '',
					intro_type: 'rich',
				},
				json: true,
				resolveWithFullResponse: true,
				headers: {},
			});
			if (resp && resp.statusCode < 300 && resp.body && resp.body.id) {
				Output(`专栏 "${title}" 创建成功`, 'info');
				vscode.window.showInformationMessage(`专栏 "${title}" 创建成功`);
				return resp.body as IColumn;
			} else {
				Output(`创建专栏 "${title}" 失败：${resp ? resp.statusCode : '无响应'}`, 'warn');
				return undefined;
			}
		} catch (error) {
			Output(`创建专栏 "${title}" 异常：${error}`, 'warn');
			return undefined;
		}
	}

	public zhihuPostExistingAnswer(html: string, questionId:string,  answerId: string, draft: boolean): Promise<boolean> {
		// No matter draft or not, new answer use post, existing answer use put
		const url = draft ? `${QuestionAPI}/${questionId}/draft` : `${AnswerAPI}/${answerId}`

		return sendRequest({
			uri: url,
			method: 'put',
			body: {
				content: html,
				reward_setting: { "can_reward": false, "tagline": "" },
			},
			json: true,
			resolveWithFullResponse: true,
			headers: {},
		}).then(resp => {
			if (!resp) {
				const errMsg = '发布失败！接口无响应，请检查网络后重试！';
				vscode.window.showWarningMessage(errMsg);
				Output(errMsg, 'warn');
				return false;
			}
			if (resp.statusCode === 200) {
				if (draft) {
					const newUrl = `${AnswerURL}/${answerId}#draft`;
					this.promptSuccessMsg(newUrl);
				} else {
					const newUrl = `${AnswerURL}/${answerId}`;
					this.promptSuccessMsg(newUrl);
					const pane = vscode.window.createWebviewPanel('zhihu', 'zhihu', vscode.ViewColumn.One, { enableScripts: true, enableCommandUris: true, enableFindWidget: true });
					sendRequest({ uri: `${AnswerURL}/${answerId}`, gzip: true }).then(
						resp => {
							pane.webview.html = resp
						}
					);
				}
				return true;
			} else {
				vscode.window.showWarningMessage(`发布失败！错误代码 ${resp.statusCode}`)
				return false;
			}
		})
	}

	public zhihuPostNewAnswer(html: string, questionId: string, draft: boolean, writeMeta?: WriteMeta): Promise<boolean> {
		// No matter draft or not, new answer use post, existing answer use put
		const url = draft ? `${QuestionAPI}/${questionId}/draft` : `${QuestionAPI}/${questionId}/answers`

		return sendRequest({
			uri: url,
			method: 'post',
			body: new PostAnswer(html),
			json: true,
			resolveWithFullResponse: true,
			headers: {}
		}).then(resp => {
			if (!resp) {
				const errMsg = '发布失败！接口无响应，请检查网络后重试！';
				vscode.window.showWarningMessage(errMsg);
				Output(errMsg, 'warn');
				return false;
			}
			if (resp.statusCode == 200) {
				if (draft) {
					const newUrl = `${QuestionURL}/${questionId}#draft`;
					this.promptSuccessMsg(newUrl);
				} else {
					const newUrl = `${AnswerURL}/${resp.body.id}`;
					writeMeta ? writeMeta("url", newUrl) : this.addMeta(vscode.window.activeTextEditor, "url", newUrl);
					this.promptSuccessMsg(newUrl);
				}
				return true;
			} else {
				if (resp.statusCode == 400 || resp.statusCode == 403) {
					vscode.window.showWarningMessage(`发布失败，你已经在该问题下发布过答案，请将头部链接更改为\
					已回答的问题下的链接。`)
				} else {
					vscode.window.showWarningMessage(`发布失败！错误代码 ${resp.statusCode}`)
				}
				return false;
			}
		})
	}

	private async zhihuArticleUpdateTags(articleId: string, tags: string[]) {
		// 1. Get topics (i.e. tags)
		const resp = await sendRequest({
			uri: `${ZhuanlanAPI}/${articleId}/draft`,
			json: true,
			method: 'get',
			headers: {}
		})
		const currentTopics = resp ? resp.topics : undefined;
		if (!Array.isArray(currentTopics)) {
			console.log("Cannot fetch topics of article", articleId);
			return;
		}
		console.log("Current topics: ", currentTopics.map(t => t.name));
		
		// 2. Delete topics which are not in the new tags
		await Promise.all(currentTopics.map(async topic => {
			if (!tags.map(x => x.toLowerCase()).includes(topic.name.toLowerCase())) {
				await sendRequest({
					uri: `${ZhuanlanAPI}/${articleId}/topics/${topic.id}`,
					method: 'delete',
					headers: {}
				})
				console.log(`Deleted topic ${topic.name}`);
			}
		}))

		// 3. Add new topics
		await Promise.all(tags.map(async tag => {
			if (!currentTopics.find(t => t.name.toLowerCase() == tag.toLowerCase())) {
				// 3.1 get info of tag
				const topicResp = await sendRequest({
					uri: `https://zhuanlan.zhihu.com/api/autocomplete/topics?token=${encodeURI(tag)}&max_matches=2&use_similar=0&topic_filter=1`,
					json: true,
					method: 'get',
					headers: {},
				})
				if (topicResp.length>0 && topicResp[0].name.toLowerCase() == tag.toLowerCase()) {
					// 3.2 add tag
					await sendRequest({
						uri: `${ZhuanlanAPI}/${articleId}/topics`,
						method: 'post',
						body: topicResp[0],
						headers: {},
						json: true
					})
					console.log(`Added topic ${tag}`);
				} else {
					console.log(`Cannot find topic ${tag}`);
				}
			}
		}))
	}

	public async zhihuPostNewArticle(content: string, title: string, tags: string[],
		column?: IColumn, titleImage?: string, draft: boolean = false, writeMeta?: WriteMeta): Promise<boolean> {
		const postResp: ITarget = await sendRequest({
			uri: `${ZhuanlanAPI}/drafts`,
			json: true,
			method: 'post',
			body: { "title": "h", "delta_time": 0 },
			headers: {
				'authority': 'zhuanlan.zhihu.com',
				'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4101.0 Safari/537.36 Edg/83.0.474.0',
				'origin': 'https://zhuanlan.zhihu.com',
				'sec-fetch-site': 'same-origin',
				'sec-fetch-mode': 'cors',
				'sec-fetch-dest': 'empty',
				'referer': 'https://zhuanlan.zhihu.com/write',
				'x-requested-with': 'fetch'
			}
		})

		// 创建草稿失败（网络错误 / 未登录 / 知乎 404 等）时 sendRequest 返回 null
		if (!postResp || !postResp.id) {
			const errMsg = '创建文章草稿失败，可能是未登录或知乎接口异常，请检查后重试！';
			vscode.window.showWarningMessage(errMsg);
			Output(errMsg, 'warn');
			return false;
		}

		let resp = await sendRequest({
			uri: `${ZhuanlanAPI}/${postResp.id}/draft`,
			json: true,
			method: 'patch',
			body: {
				content: content,
				title: title,
				titleImage,
				isTitleImageFullScreen: vscode.workspace.getConfiguration('zhihu').get(SettingEnum.isTitleImageFullScreen)
			},
			headers: {}
		})

		this.zhihuArticleUpdateTags(`${postResp.id}`, tags);

		if (draft) {
			writeMeta ? writeMeta("url", `${ZhuanlanURL}${postResp.id}`) : this.addMeta(vscode.window.activeTextEditor, "url", `${ZhuanlanURL}${postResp.id}`);
			this.promptSuccessMsg(`${ZhuanlanURL}${postResp.id}/edit`, `Draft: ${title}`)
			return true;
		}

		resp = await sendRequest({
			uri: `${ZhuanlanAPI}/${postResp.id}/publish`,
			json: true,
			method: 'put',
			body: { "column": column, "commentPermission": "anyone" },
			headers: {},
			resolveWithFullResponse: true
		})
		if (!resp) {
			const errMsg = '文章发布失败，接口无响应，请检查网络后重试！';
			vscode.window.showWarningMessage(errMsg);
			Output(errMsg, 'warn');
			return false;
		}
		if (resp.statusCode < 300) {
			writeMeta ? writeMeta("url", `${ZhuanlanURL}${postResp.id}`) : this.addMeta(vscode.window.activeTextEditor, "url", `${ZhuanlanURL}${postResp.id}`);
			this.promptSuccessMsg(`${ZhuanlanURL}${postResp.id}`, title)
			return true;
		} else {
			vscode.window.showWarningMessage(`文章发布失败，错误代码${resp.statusCode}`)
			return false;
		}
	}

	public async zhihuPostExistingArticle(content: string, articleId: string, title: string, tags: string[],
			column?: IColumn, titleImage?: string, draft: boolean = false): Promise<boolean> {
		this.zhihuArticleUpdateTags(articleId, tags);

		let resp = await sendRequest({
			uri: `${ZhuanlanAPI}/${articleId}/draft`,
			json: true,
			method: 'patch',
			body: {
				content: content,
				title: title,
				titleImage,
				isTitleImageFullScreen: vscode.workspace.getConfiguration('zhihu').get(SettingEnum.isTitleImageFullScreen)
			},
			headers: {}
		})

		if (draft) {
			this.promptSuccessMsg(`${ZhuanlanURL}${articleId}/edit`, `Draft: ${title}`)
			return true;
		}

		resp = await sendRequest({
			uri: `${ZhuanlanAPI}/${articleId}/publish`,
			json: true,
			method: 'put',
			body: { "column": column, "commentPermission": "anyone" },
			headers: {},
			resolveWithFullResponse: true
		})
		if (!resp) {
			const errMsg = '文章发布失败，接口无响应，请检查网络后重试！';
			vscode.window.showWarningMessage(errMsg);
			Output(errMsg, 'warn');
			return false;
		}
		if (resp.statusCode < 300) {
			this.promptSuccessMsg(`${ZhuanlanURL}${articleId}`, title)
			return true;
		} else {
			vscode.window.showWarningMessage(`文章发布失败，错误代码${resp.statusCode}`)
			return false;
		}
	}

	private promptSuccessMsg(url: string, title?: string) {
		// 非模态提示，显示在 VS Code 右下角，不打断用户操作
		vscode.window.showInformationMessage(`${title ? '"' + title + '"' : ''} 发布成功！`,
			previewActions.openInBrowser
		).then(r => r ? vscode.env.openExternal(vscode.Uri.parse(url)) : undefined);
	}

	shebangParser(text: string): URL {
		const shebangRegExp = /#[!！]\s*((https?:\/\/)?(.+))$/i
		let lf = text.indexOf('\n');
		if (lf < 0) lf = text.length;
		let link = text.slice(0, lf);
		link = link.indexOf('\r') > 0 ? link.slice(0, link.length - 1) : link;
		if (!shebangRegExp.test(link)) return undefined;
		const url = new URL(link.replace(shebangRegExp, '$1'));
		if (/^(\w)+\.zhihu\.com$/.test(url.host)) return url;
		else return undefined;
		// shebangRegExp = /(https?:\/\/)/i
	}
}
