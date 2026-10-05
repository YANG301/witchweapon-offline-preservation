package main

import (
	"html/template"
	"strings"
	texttemplate "text/template"
)

const emailVerificationSubject = "魔女兵器邮箱验证码"

const emailVerificationText = `魔女兵器
WITCH WEAPON / REUNION

您的邮箱验证码：{{.Code}}

验证码在 30 分钟内有效，请勿向他人透露。
请返回游戏「设置 → 个人中心」，输入这 6 位验证码，完成当前注册邮箱的验证。

如果这不是您本人的操作，请忽略本邮件。
魔女兵器 Wiki：https://www.witchweapon.wiki/
`

// Table layout, presentation attributes and inline styles keep the essential
// content readable in Outlook without external fonts or style sheets. The
// fixed Wiki background is decorative; opaque colors keep the text readable.
const emailVerificationHTML = `<!doctype html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>魔女兵器邮箱验证</title></head>
<body style="margin:0;padding:0;background-color:#11131e;color:#f1eee5;">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">返回游戏个人中心，完成当前注册邮箱的验证。</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#11131e" style="width:100%;background-color:#11131e;border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt;">
<tr><td align="center" style="padding:32px 12px;">
{{.OutlookOpen}}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt;">
<tr><td height="3" bgcolor="#d5bce9" style="height:3px;font-size:0;line-height:3px;background-color:#d5bce9;">&nbsp;</td></tr>
<tr><td background="https://www.witchweapon.wiki/assets/spring.png" bgcolor="#11131e" height="180" valign="middle" style="height:180px;background-color:#11131e;background-image:url('https://www.witchweapon.wiki/assets/spring.png');background-size:cover;background-position:center center;background-repeat:no-repeat;">
{{.OutlookHeroOpen}}
<table role="presentation" width="100%" height="180" cellpadding="0" cellspacing="0" border="0" style="width:100%;height:180px;border-collapse:collapse;">
<tr><td valign="middle" style="padding:24px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#11131e" style="width:100%;max-width:320px;border-collapse:collapse;background-color:#11131e;">
<tr><td bgcolor="#11131e" style="padding:18px 20px;background-color:#11131e;">
<p style="margin:0 0 12px;color:#f1eee5;font-family:SimSun,'Songti SC',Georgia,serif;font-size:30px;line-height:42px;letter-spacing:6px;">魔女兵器</p>
<p style="margin:0;color:#d5bce9;font-family:Georgia,'Times New Roman',serif;font-size:11px;line-height:18px;letter-spacing:2px;">WITCH WEAPON / REUNION</p>
</td></tr></table>
</td></tr></table>
{{.OutlookHeroClose}}
</td></tr>
<tr><td bgcolor="#f1eee5" style="padding:30px 24px 32px;background-color:#f1eee5;color:#11131e;font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;">
<p style="margin:0 0 10px;color:#11131e;font-family:SimSun,'Songti SC',Georgia,serif;font-size:26px;line-height:38px;letter-spacing:2px;">验证你的邮箱</p>
<p style="margin:0 0 22px;font-size:14px;line-height:26px;">请使用以下 6 位验证码，完成当前注册邮箱的验证。</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#d5bce9" style="width:100%;border-collapse:collapse;background-color:#d5bce9;">
<tr><td align="center" style="padding:10px 8px;color:#11131e;font-family:'Courier New',Courier,monospace;font-size:44px;font-weight:bold;line-height:68px;letter-spacing:6px;white-space:nowrap;mso-line-height-rule:exactly;">{{.Code}}</td></tr>
</table>
<p style="margin:14px 0 24px;text-align:center;font-size:13px;line-height:22px;">30 分钟内有效 · 请勿向他人透露</p>
<p style="margin:0 0 20px;font-size:14px;line-height:26px;">请返回游戏<strong>「设置 → 个人中心」</strong>，输入验证码并完成验证。</p>
<p style="margin:18px 0 0;font-size:12px;line-height:22px;">如果这不是您本人的操作，请忽略本邮件。</p>
</td></tr>
<tr><td bgcolor="#11131e" style="padding:24px;color:#b2b8b5;background-color:#11131e;font-family:'Microsoft YaHei','PingFang SC',Arial,sans-serif;font-size:12px;line-height:24px;">
<p style="margin:0;">魔女兵器 Wiki<br><a href="https://www.witchweapon.wiki/" style="color:#d5bce9;text-decoration:underline;">www.witchweapon.wiki</a></p>
</td></tr>
</table>
{{.OutlookClose}}
</td></tr></table>
</body>
</html>`

var emailVerificationHTMLTemplate = template.Must(template.New("email-verification").Parse(emailVerificationHTML))
var emailVerificationTextTemplate = texttemplate.Must(texttemplate.New("email-verification-text").Parse(emailVerificationText))

func renderEmailVerification(code string) (string, string, error) {
	// html/template removes literal comments. Only these fixed Outlook table/VML
	// wrappers are trusted HTML; the verification code stays an escaped string.
	data := struct {
		Code             string
		OutlookOpen      template.HTML
		OutlookClose     template.HTML
		OutlookHeroOpen  template.HTML
		OutlookHeroClose template.HTML
	}{code,
		template.HTML(`<!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->`),
		template.HTML(`<!--[if mso]></td></tr></table><![endif]-->`),
		template.HTML(`<!--[if mso]><v:rect xmlns:v="urn:schemas-microsoft-com:vml" fill="true" stroke="false" style="width:600px;height:180px;"><v:fill type="frame" src="https://www.witchweapon.wiki/assets/spring.png" color="#11131e" /><v:textbox inset="0,0,0,0"><![endif]-->`),
		template.HTML(`<!--[if mso]></v:textbox></v:rect><![endif]-->`)}
	var plain, html strings.Builder
	if err := emailVerificationTextTemplate.Execute(&plain, data); err != nil {
		return "", "", err
	}
	if err := emailVerificationHTMLTemplate.Execute(&html, data); err != nil {
		return "", "", err
	}
	return plain.String(), html.String(), nil
}
