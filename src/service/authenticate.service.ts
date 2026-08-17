import * as crypto from "crypto";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import * as zhihuEncrypt from "zhihu-encrypt";
import { DefaultHTTPHeader, LoginPostHeader } from "../const/HTTP";
import { TemplatePath } from "../const/PATH";
import { CaptchaAPI, LoginAPI, SMSAPI } from "../const/URL";
import { ILogin, ISmsData } from "../model/login.model";
import { LoginEnum, LoginTypes, SettingEnum } from "../const/ENUM";
import { AccountService } from "./account.service";
import { HttpService, clearCookie, sendRequest, setXsrfToken } from "./http.service";
import { ProfileService } from "./profile.service";
import { WebviewService } from "./webview.service";
import { getExtensionPath } from "../global/globa-var";
import { getCookieJar } from "../global/cookie";
import { Output } from "../global/logger";
import * as cookieUtil from "tough-cookie";

var formurlencoded = require('form-urlencoded').default;

export class AuthenticateService {
	constructor(
		protected profileService: ProfileService,
		protected accountService: AccountService,
		protected webviewService: WebviewService) {
	}
	public logout() {
		try {
			clearCookie();
			// fs.writeFileSync(path.join(getExtensionPath(), 'cookie.txt'), '');
		} catch (error) {
			console.log(error);
		}
		vscode.window.showInformationMessage('注销成功！');
	}

	public async login() {
		if (await this.accountService.isAuthenticated()) {
			vscode.window.showInformationMessage(`你已经登录了哦~ ${this.profileService.name}`);
			return;
		}
		clearCookie()
		const selectedLoginType: LoginEnum = await vscode.window.showQuickPick<vscode.QuickPickItem & { value: LoginEnum }>(
			LoginTypes.map(type => ({ value: type.value, label: type.ch, description: '' })),
			{ placeHolder: "选择登录方式: " }
		).then(item => {
			// 用户按 ESC 取消时 item 为 undefined，避免读取 undefined.value 崩溃
			return item ? item.value : undefined;
		});

		if (selectedLoginType == undefined || selectedLoginType === null) {
			return;
		}

		if (selectedLoginType == LoginEnum.password) {
			this.passwordLogin();
		} else if (selectedLoginType == LoginEnum.sms) {
			this.smsLogin();
		} else if (selectedLoginType == LoginEnum.cookie) {
			this.cookieLogin();
		}
	}

	/**
	 * 通过粘贴 Cookie 登录知乎
	 *
	 * 用户从浏览器（已登录知乎）中复制 Cookie 字符串后粘贴到输入框，
	 * 插件会解析这些 Cookie 并写入本地的 cookie jar，从而完成登录。
	 *
	 * 支持两种粘贴格式：
	 *  - 浏览器里的原始 Cookie 字符串，例如：
	 *      `z_c0=xxxxx; d_c0=xxxxx; _xsrf=xxxxx`
	 *  - 复制自「开发者工具 -> Network -> 请求头」中的完整 Cookie 值
	 *    （此时可能包含 `cookie:` 前缀，会被自动去除）
	 */
	public async cookieLogin() {
		const rawCookie: string | undefined = await vscode.window.showInputBox({
			ignoreFocusOut: true,
			prompt: "请粘贴知乎的 Cookie（在浏览器中登录知乎后复制）",
			placeHolder: "粘贴 Cookie，例如: _xsrf=xxx; z_c0=xxx; ...",
			password: true
		});
		if (!rawCookie) {
			return;
		}

		// 兼容形如 `cookie: _xsrf=xxx; z_c0=xxx` 的完整请求头粘贴
		let cookieStr = rawCookie.trim();
		if (cookieStr.toLowerCase().startsWith('cookie:')) {
			cookieStr = cookieStr.slice('cookie:'.length).trim();
		}

		// 先清空旧的登录态，避免残留 Cookie 干扰
		clearCookie();

		const jar = getCookieJar();
		const url = 'https://www.zhihu.com';
		let parsedCount = 0;
		cookieStr.split(';').forEach(pair => {
			const idx = pair.indexOf('=');
			if (idx < 0) {
				return;
			}
			const key = pair.slice(0, idx).trim();
			const value = pair.slice(idx + 1).trim();
			if (!key) {
				return;
			}
			try {
				// 显式声明 domain 为 .zhihu.com，让 Cookie 对所有知乎子域生效
				const cookie = new cookieUtil.Cookie({
					key,
					value,
					domain: 'zhihu.com',
					path: '/'
				});
				jar.setCookieSync(cookie, url);
				parsedCount++;
			} catch (error) {
				console.log(error);
			}
		});

		if (parsedCount === 0) {
			vscode.window.showWarningMessage('未解析到有效的 Cookie，请检查后重试。');
			return;
		}

		// 更新 XSRF token，供后续接口鉴权使用
		try {
			const xsrfCookie = jar.getCookieStringSync(url).match(/(?:^|;\s*)_xsrf=([^;]*)/);
			if (xsrfCookie) {
				setXsrfToken(xsrfCookie[1]);
			}
		} catch (error) {
			console.log(error);
		}

		// 验证登录态并拉取用户信息
		try {
			await this.profileService.fetchProfile();
			if (this.profileService.name) {
				vscode.window.showInformationMessage(`你好，${this.profileService.name}，登录成功！`);
			} else {
				vscode.window.showWarningMessage('Cookie 已写入，但未能获取到用户信息，请检查 Cookie 是否有效或已过期。');
			}
		} catch (error) {
			vscode.window.showWarningMessage('登录失败，请检查 Cookie 是否有效或已过期。');
			console.log(error);
		}
	}

	public async passwordLogin() {
		let resp = await sendRequest({
			uri: CaptchaAPI,
			method: 'get',
			gzip: true,
			json: true
		});

		if (resp.show_captcha) {
			let captchaImg = await sendRequest({
				uri: CaptchaAPI,
				method: 'put',
				json: true,
				gzip: true
			});
			let base64Image = captchaImg['img_base64'].replace('\n', '');
			fs.writeFileSync(path.join(getExtensionPath(), './captcha.jpg'), base64Image, 'base64');
			const panel = vscode.window.createWebviewPanel("zhihu", "验证码", { viewColumn: vscode.ViewColumn.One, preserveFocus: true });
			const imgSrc = panel.webview.asWebviewUri(vscode.Uri.file(
				path.join(getExtensionPath(), './captcha.jpg')
			));

			this.webviewService.renderHtml({
				title: '验证码',
				showOptions: {
					viewColumn: vscode.ViewColumn.One,
					preserveFocus: true
				},
				pugTemplatePath: path.join(
					getExtensionPath(),
					TemplatePath,
					'captcha.pug'
				),
				pugObjects: {
					title: '验证码',
					captchaSrc: imgSrc.toString(),
					useVSTheme: vscode.workspace.getConfiguration('zhihu').get(SettingEnum.useVSTheme)
				}
			}, panel)

			do {
				var captcha: string | undefined = await vscode.window.showInputBox({
					prompt: "输入验证码",
					placeHolder: "",
					ignoreFocusOut: true
				});
				if (!captcha) return
				let headers = DefaultHTTPHeader;
				headers['cookie'] = fs.readFileSync
				resp = await sendRequest({
					method: 'POST',
					uri: CaptchaAPI,
					form: {
						input_text: captcha
					},
					json: true,
					simple: false,
					gzip: true,
					resolveWithFullResponse: true,
				});
				if (resp.statusCode != 201) {
					vscode.window.showWarningMessage('请输入正确的验证码')
				}
			} while (resp.statusCode != 201);
			Output('验证码正确。', 'info')
			panel.dispose()
		}

		const phoneNumber: string | undefined = await vscode.window.showInputBox({
			ignoreFocusOut: true,
			prompt: "输入手机号或邮箱",
			placeHolder: "",
		});
		if (!phoneNumber) return;

		const password: string | undefined = await vscode.window.showInputBox({
			ignoreFocusOut: true,
			prompt: "输入密码",
			placeHolder: "",
			password: true
		});
		if (!password) return

		let loginData: ILogin = {
			'client_id': 'c3cef7c66a1843f8b3a9e6a1e3160e20',
			'grant_type': 'password',
			'source': 'com.zhihu.web',
			'username': '+86' + phoneNumber,
			'password': password,
			'lang': 'en',
			'ref_source': 'homepage',
			'utm_source': '',
			'captcha': captcha,
			'timestamp': Math.round(new Date().getTime()),
			'signature': ''
		};

		loginData.signature = crypto.createHmac('sha1', 'd1b964811afb40118a12068ff74a12f4')
			// .update(loginData.grant_type + loginData.client_id + loginData.source + loginData.timestamp.toString())
			.update("password" + loginData.client_id + loginData.source + loginData.timestamp.toString())
			.digest('hex');

		let encryptedFormData = zhihuEncrypt.loginEncrypt(formurlencoded(loginData));

		var loginResp = await sendRequest(
			{
				uri: LoginAPI,
				method: 'post',
				body: encryptedFormData,
				gzip: true,
				resolveWithFullResponse: true,
				simple: false,
				headers: LoginPostHeader
			});

		this.profileService.fetchProfile().then(() => {
			if (loginResp.statusCode == '201') {
				Output(`你好，${this.profileService.name}`, 'info');
			} else if (loginResp.statusCode == '401') {
				Output('密码错误！' + loginResp.statusCode, 'warn');
			} else {
				Output('登录失败！错误代码' + loginResp.statusCode, 'warn');
			}
		})
	}

	public async smsLogin() {
		await sendRequest({
			uri: 'https://www.zhihu.com/signin'
		})
		const phoneNumber: string | undefined = await vscode.window.showInputBox({
			ignoreFocusOut: true,
			prompt: "输入手机号或邮箱",
			placeHolder: "",
		});
		if (!phoneNumber) {
			return;
		}
		let smsData: ISmsData = {
			phone_no: '+86' + phoneNumber,
			sms_type: 'text'
		};

		let encryptedFormData = zhihuEncrypt.smsEncrypt(formurlencoded(smsData));

		// phone_no%3D%252B8618324748963%26sms_type%3Dtext
		var loginResp = await sendRequest(
			{
				uri: SMSAPI,
				method: 'post',
				body: encryptedFormData,
				gzip: true,
				resolveWithFullResponse: true,
				simple: false,
				json: true
			});
		console.log(loginResp);
		const smsCaptcha: string | undefined = await vscode.window.showInputBox({
			ignoreFocusOut: true,
			prompt: "输入短信验证码：",
			placeHolder: "",
		});
	}

	}
