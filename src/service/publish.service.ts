import * as vscode from "vscode";
import { MediaTypes, SettingEnum } from "../const/ENUM";
import { ArticlePathReg, QuestionAnswerPathReg, QuestionPathReg } from "../const/REG";
import { AnswerAPI, AnswerURL, QuestionAPI, QuestionURL, ZhuanlanAPI, ZhuanlanURL } from "../const/URL";
import { PostAnswer } from "../model/publish/answer.model";
import { IColumn } from "../model/publish/column.model";
import { IProfile, ITarget } from "../model/target/target";
import { EventService } from "./event.service";
import { sendRequest } from "./http.service";
import { ProfileService } from "./profile.service";
import { WebviewService } from "./webview.service";
import * as MarkdownIt from "markdown-it";
import md5 = require("md5");
import { PasteService } from "./paste.service";
import { PipeService } from "./pipe.service";

enum previewActions {
	openInBrowser = '去看看'
}

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
		const url: URL|undefined = meta['zhihu-url'] && new URL(meta['zhihu-url']);
		if (url === undefined)
			return true;
		
		if (QuestionAnswerPathReg.test(url.pathname) || QuestionPathReg.test(url.pathname))
			return false;

		return true;
	}

	private async renderZhihuMarkdown(textEditor: vscode.TextEditor): Promise<string> {
		const text = textEditor.document.getText();
		// text = text + "\n\n>本文使用 [zhihupost]发布 [@GitHub](https://github.com/keindex/zhihupost)";

		/// Render markdown

		// Running render on markdown without meta will return meta from the previous run
		// Refer to https://github.com/CaliStyle/markdown-it-meta/issues/5
		(this.zhihuMdParser as any).meta = undefined;
		const tokens = this.zhihuMdParser.parse(text, {});
		// convert local and outer link to zhihu link
		const pipePromise = this.pipeService.sanitizeMdTokens(tokens);
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
		const meta_template = `---
title: 
zhihu-url: 
zhihu-title-image: 
zhihu-column: 
zhihu-tags: 
---
`
		textEditor.edit(e => {
			e.insert(new vscode.Position(0, 0), meta_template);
		})
	}

	private async getQuestionIdOfAnswer(url: string): Promise<string> {	
		return sendRequest({
			uri: url,
			method: 'get',
			resolveWithFullResponse: true,
			headers: {},
		}).then(resp => resp.request.href.match(/(\/question\/(\d+))?\/answer\/(\d+)$/i)[2]);
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

		let title: string|undefined = meta.title;
		// 元数据未指定标题时，默认取 md 文件的第一行文字作为标题
		if (!title) {
			title = this._getTitleFromDocument(textEditor);
		}
		let titleImage: string|undefined = meta['zhihu-title-image'];
		const url: URL|undefined = meta['zhihu-url'] && new URL(meta['zhihu-url']);
		if (titleImage !== undefined) {
			titleImage = await this.pasteService.uploadImageFromLink(titleImage);
			console.log('titleImage', titleImage);
		}
		const articleTags: string[] = meta['zhihu-tags'] ? meta['zhihu-tags'].split(',').map((x: string)=>x.trim()) : [];

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
				if (!this.eventService.registerEvent({
					content: html,
					type: MediaTypes.article,
					date: new Date(),
					hash: md5(html),
					handler: () => {
						this.zhihuPostExistingAnswer(html, questionId, answerId, draft);
						this.eventService.destroyEvent(md5(html));
					}
				})) this.promptSameContentWarn()
			} else if (QuestionPathReg.test(url.pathname)) {
				// Link like https://www.zhihu.com/question/481576477
				// question link, post new answer
				const questionId = url.pathname.replace(QuestionPathReg, '$1');
				if (!this.eventService.registerEvent({
					content: html,
					type: MediaTypes.question,
					date: new Date(),
					hash: md5(html),
					handler: () => {
						this.zhihuPostNewAnswer(html, questionId, draft);
						this.eventService.destroyEvent(md5(html));
					}
				})) this.promptSameContentWarn()
			} else if (ArticlePathReg.test(url.pathname)) {
				// Link like https://zhuanlan.zhihu.com/p/390528313
				const articleId = url.pathname.replace(ArticlePathReg, '$1');
				if (!title) {
					title = await this._getTitle();
					if (title) {
						this.addMeta(textEditor, 'title', title);
					} else {
						vscode.window.showErrorMessage('标题不对，中止');
						return;
					}
				}
				const column = await this._getColumnFromMeta(meta);
				if (!this.eventService.registerEvent({
					content: html,
					type: MediaTypes.question,
					date: new Date(),
					title: title,
					hash: md5(html),
					handler: () => {
						this.zhihuPostExistingArticle(html, articleId, title, articleTags, column, titleImage, draft);
						this.eventService.destroyEvent(md5(html));
					}
				})) this.promptSameContentWarn()
			}
		} else { // url is not provided
			// 没有 url 时直接发布新文章（不再提供「从收藏夹中选取」选项）
			if (!title) {
				title = await this._getTitle();
				if (title) {
					this.addMeta(textEditor, 'title', title);
				} else {
					vscode.window.showErrorMessage('标题不对，中止');
					return;
				}
			}
			const column = await this._getColumnFromMeta(meta);
			if (!title) return;
			if (!this.eventService.registerEvent({
				content: html,
				type: MediaTypes.article,
				title,
				date: new Date(),
				hash: md5(html + title),
				handler: () => {
					this.zhihuPostNewArticle(html, title, articleTags, column, titleImage, draft);
					this.eventService.destroyEvent(md5(html + title));
				}
			})) this.promptSameContentWarn()
		}
	}

	private promptSameContentWarn() {
		vscode.window.showWarningMessage(`你已经有一篇一模一样的内容还未发布！`);
	}

	/**
	 * 从 md 文件的第一行正文中提取标题。
	 *
	 * 元数据（`---` 包裹的部分）位于文件头部，正文第一行通常是 `# 标题`，
	 * 去掉 markdown 标题标记（`#`）后即为标题。
	 */
	private _getTitleFromDocument(textEditor: vscode.TextEditor): string | undefined {
		const lines = textEditor.document.getText().split(/\r?\n/);
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
	 * 从 md 文件的元数据 `zhihu-column` 中读取目标专栏标题，并匹配出对应的专栏。
	 *
	 * 若元数据中未指定专栏（`zhihu-column` 缺失或为空），则返回 undefined，
	 * 表示不发布到任何专栏。
	 */
	private async _getColumnFromMeta(meta: any): Promise<IColumn | undefined> {
		const columnTitle: string | undefined = meta && meta['zhihu-column'];
		if (!columnTitle || !columnTitle.trim()) return undefined;

		const columns = await this.profileService.getColumns();
		if (!columns || columns.length === 0) {
			vscode.window.showWarningMessage(`未获取到你的专栏列表，无法发布到专栏 "${columnTitle.trim()}"`);
			return undefined;
		}

		const column = columns.find(c => c.title === columnTitle.trim());
		if (!column) {
			vscode.window.showWarningMessage(`未找到专栏 "${columnTitle.trim()}"，请检查元数据中的 zhihu-column 是否正确。`);
		}
		return column;
	}

	public zhihuPostExistingAnswer(html: string, questionId:string,  answerId: string, draft: boolean) {
		// No matter draft or not, new answer use post, existing answer use put
		const url = draft ? `${QuestionAPI}/${questionId}/draft` : `${AnswerAPI}/${answerId}`

		sendRequest({
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
			} else {
				vscode.window.showWarningMessage(`发布失败！错误代码 ${resp.statusCode}`)
			}
		})
	}

	public zhihuPostNewAnswer(html: string, questionId: string, draft: boolean) {
		// No matter draft or not, new answer use post, existing answer use put
		const url = draft ? `${QuestionAPI}/${questionId}/draft` : `${QuestionAPI}/${questionId}/answers`

		sendRequest({
			uri: url,
			method: 'post',
			body: new PostAnswer(html),
			json: true,
			resolveWithFullResponse: true,
			headers: {}
		}).then(resp => {
			if (resp.statusCode == 200) {
				if (draft) {
					const newUrl = `${QuestionURL}/${questionId}#draft`;
					this.promptSuccessMsg(newUrl);
				} else {
					const newUrl = `${AnswerURL}/${resp.body.id}`;
					this.addMeta(vscode.window.activeTextEditor, "zhihu-url", newUrl);
					this.promptSuccessMsg(newUrl);
				}
			} else {
				if (resp.statusCode == 400 || resp.statusCode == 403) {
					vscode.window.showWarningMessage(`发布失败，你已经在该问题下发布过答案，请将头部链接更改为\
					已回答的问题下的链接。`)
				} else {
					vscode.window.showWarningMessage(`发布失败！错误代码 ${resp.statusCode}`)
				}
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
		const currentTopics = resp.topics;
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
		column?: IColumn, titleImage?: string, draft: boolean = false) {
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
			this.addMeta(vscode.window.activeTextEditor, "zhihu-url", `${ZhuanlanURL}${postResp.id}`);
			this.promptSuccessMsg(`${ZhuanlanURL}${postResp.id}/edit`, `Draft: ${title}`)
			return resp;
		}

		resp = await sendRequest({
			uri: `${ZhuanlanAPI}/${postResp.id}/publish`,
			json: true,
			method: 'put',
			body: { "column": column, "commentPermission": "anyone" },
			headers: {},
			resolveWithFullResponse: true
		})
		if (resp.statusCode < 300) {
			this.addMeta(vscode.window.activeTextEditor, "zhihu-url", `${ZhuanlanURL}${postResp.id}`);
			this.promptSuccessMsg(`${ZhuanlanURL}${postResp.id}`, title)
		} else {
			vscode.window.showWarningMessage(`文章发布失败，错误代码${resp.statusCode}`)
		}
		return resp;
	}

	public async zhihuPostExistingArticle(content: string, articleId: string, title: string, tags: string[],
			column?: IColumn, titleImage?: string, draft: boolean = false) {
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
			return resp;
		}

		resp = await sendRequest({
			uri: `${ZhuanlanAPI}/${articleId}/publish`,
			json: true,
			method: 'put',
			body: { "column": column, "commentPermission": "anyone" },
			headers: {},
			resolveWithFullResponse: true
		})
		if (resp.statusCode < 300) {
			this.promptSuccessMsg(`${ZhuanlanURL}${articleId}`, title)
		} else {
			vscode.window.showWarningMessage(`文章发布失败，错误代码${resp.statusCode}`)
		}
		return resp;
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
