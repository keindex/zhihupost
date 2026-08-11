export enum MediaTypes {
	answer = 'answer',
	question = 'question',
	article = 'article'
}

export enum SearchTypes {
	general = 'general',
	question = 'question',
	answer = 'answer',
	article = 'article'
}

export enum Weekdays {
	Mon = 'Mon',
	Tue = 'Tue',
	Wed = 'Wed',
	Tur = 'Tur',
	Fri = 'Fri',
	Sat = 'Sat',
	Sun = 'Sun'
}

export const WeekdaysDict = {
	Mon: 1,
	Tue: 2,
	Wed: 3,
	Tur: 4,
	Fri: 5,
	Sat: 6,
	Sun: 7
}

export const LegalImageExt = [ '.jpg', '.jpeg', '.gif', '.png' ]; 

export enum LoginEnum {
	sms,
	password,
	cookie
}

export const LoginTypes = [
	{ value: LoginEnum.cookie, ch: '粘贴 Cookie'},
	// { value: LoginEnum.sms, ch: '短信验证码' },
	// { value: LoginEnum.password, ch: '密码' },
]

export enum SettingEnum {
	useVSTheme = 'useVSTheme',
	isTitleImageFullScreen = 'isTitleImageFullScreen'
}

export enum WebviewEvents {
	share = 'share',
	open = 'open',
	upvoteAnswer = 'upvoteAnswer',
	upvoteArticle = 'upvoteArticle'
}