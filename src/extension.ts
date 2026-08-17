"use strict";

import * as fs from "fs";
import * as MarkdownIt from "markdown-it";
import markdown_it_zhihu from "markdown-it-zhihu-common";
import * as meta from "markdown-it-meta"; // import meta from "markdown-it-meta"; not working why?
import * as path from "path";
import * as vscode from "vscode";
import { AccountService } from "./service/account.service";
import { AuthenticateService } from "./service/authenticate.service";
import { EventService } from "./service/event.service";
import { HttpService, clearCache } from "./service/http.service";
import { PasteService } from "./service/paste.service";
import { PipeService } from "./service/pipe.service";
import { ProfileService } from "./service/profile.service";
import { PublishService } from "./service/publish.service";
import { SearchService } from "./service/search.service";
import { WebviewService } from "./service/webview.service";
import { setContext } from "./global/globa-var";
import { Output } from "./global/logger";
import * as CacheManager from "./global/cache"
import { ZhihuCompletionProvider, AtPeople } from "./lang/completion-provider";

export async function activate(context: vscode.ExtensionContext) {
	Output('Extension Activated')
	if(!fs.existsSync(path.join(context.extensionPath, './cookie.json'))) {
		fs.createWriteStream(path.join(context.extensionPath, './cookie.json')).end()
	}
	setContext(context);
	// Dependency Injection
	const zhihuMdParser = new MarkdownIt({ html: true }).use(markdown_it_zhihu).use(meta);
	const defualtMdParser = new MarkdownIt();
	const accountService = new AccountService();
	const profileService = new ProfileService(accountService);
	await profileService.fetchProfile();
	const webviewService = new WebviewService();
	const eventService = new EventService();
	const searchService = new SearchService(webviewService);
	const authenticateService = new AuthenticateService(profileService, accountService, webviewService);
	const pasteService = new PasteService();
	const pipeService = new PipeService(pasteService);
	const publishService = new PublishService(zhihuMdParser, defualtMdParser, webviewService, eventService, profileService, pasteService, pipeService);


	context.subscriptions.push(
		vscode.commands.registerCommand("zhihu.openWebView", async (object) => {
			await webviewService.openWebview(object);
		}
		));
	vscode.commands.registerCommand("zhihu.search", async () => 
		await searchService.getSearchItems()
	);
	vscode.commands.registerCommand("zhihu.clearCache", () => {
		clearCache()
		CacheManager.clearCache()
	})
	vscode.commands.registerCommand("zhihu.login", () => 
		authenticateService.login()
	);
	vscode.commands.registerCommand("zhihu.logout", () =>
		authenticateService.logout()
	);
	vscode.commands.registerTextEditorCommand('zhihu.publish', (textEditor: vscode.TextEditor, edit: vscode.TextEditorEdit) => {
		publishService.publish(textEditor, edit, false);
	})
	vscode.commands.registerTextEditorCommand('zhihu.drafts', (textEditor: vscode.TextEditor, edit: vscode.TextEditorEdit) => {
		publishService.publish(textEditor, edit, true);
	})
	vscode.commands.registerCommand('zhihu.publishFile', (uri: vscode.Uri) => {
		if (!uri || !uri.fsPath) {
			vscode.window.showErrorMessage('请选择一个 Markdown 文件');
			return;
		}
		publishService.publishFile(uri.fsPath, false);
	})
	vscode.commands.registerCommand('zhihu.publishFileAsDraft', (uri: vscode.Uri) => {
		if (!uri || !uri.fsPath) {
			vscode.window.showErrorMessage('请选择一个 Markdown 文件');
			return;
		}
		publishService.publishFile(uri.fsPath, true);
	})
	vscode.commands.registerCommand('zhihu.publishFolder', (uri: vscode.Uri) => {
		if (!uri || !uri.fsPath) {
			vscode.window.showErrorMessage('请选择一个文件夹');
			return;
		}
		publishService.publishFolder(uri, false);
	})
	vscode.commands.registerCommand('zhihu.publishFolderAsDrafts', (uri: vscode.Uri) => {
		if (!uri || !uri.fsPath) {
			vscode.window.showErrorMessage('请选择一个文件夹');
			return;
		}
		publishService.publishFolder(uri, true);
	})
	vscode.commands.registerCommand('zhihu.uploadImageFromClipboard', async () => {
		pasteService.uploadImageFromClipboard()
	})

	vscode.commands.registerCommand('zhihu.uploadImageFromPath', (uri: vscode.Uri) => {
		pasteService.uploadImageFromPath(uri)
	})

	vscode.commands.registerCommand('zhihu.uploadImageFromExplorer', () => {
		pasteService.uploadImageFromExplorer()
	})
	vscode.commands.registerCommand("zhihu.atPeople", () => {
		AtPeople()
	})
	context.subscriptions.push(vscode.languages.registerCompletionItemProvider('markdown', new ZhihuCompletionProvider
	, '@'));


	return {
        extendMarkdownIt(md: any) {
            return md.use(require('markdown-it-katex'));
        }
    }
}