
import { SelfProfileAPI } from "../const/URL";
import { IProfile } from "../model/target/target";
import { sendRequest } from "./http.service";
import { getCookieJar } from "../global/cookie";


export class AccountService {
	public profile: IProfile;

	constructor () {}

	async fetchProfile() {
		this.profile  = await sendRequest({
			uri: SelfProfileAPI,
			json: true
		});
	}

	/**
	 * 判断是否已登录知乎。
	 *
	 * 通过检查本地 cookie jar 中是否存在知乎的登录凭据 cookie（如 `z_c0`）
	 * 来判断登录状态，而不是依赖请求 `/signup` 页面的重定向状态码。
	 * 因为知乎会对任意访问 `/signup` 的请求（无论是否登录）都返回 302 重定向，
	 * 导致原来的判断逻辑误判为「已登录」。
	 */
	async isAuthenticated(): Promise<boolean> {
		try {
			const cookieJar = getCookieJar();
			const cookieString = cookieJar.getCookieStringSync('https://www.zhihu.com');

			// 知乎登录后必带的核心登录 cookie 为 `z_c0`，以此作为登录凭据
			return /(?:^|;\s*)z_c0=/.test(cookieString);
		} catch (err) {
			console.error('isAuthenticated error', err);
			return false;
		}
	}

}