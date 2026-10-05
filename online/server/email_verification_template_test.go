package main

import (
	"regexp"
	"strings"
	"testing"
)

func TestEmailVerificationTemplateContent(t *testing.T) {
	plain, html, err := renderEmailVerification("012345")
	if err != nil {
		t.Fatal(err)
	}
	for _, required := range []string{"魔女兵器", "WITCH WEAPON / REUNION", "012345", "30 分钟", "设置 → 个人中心", "如果这不是您本人的操作，请忽略本邮件。", "魔女兵器 Wiki"} {
		if !strings.Contains(plain, required) || !strings.Contains(html, required) {
			t.Errorf("HTML or plaintext lacks %q", required)
		}
	}
	if !strings.Contains(plain, "https://www.witchweapon.wiki/") || !strings.Contains(html, `href="https://www.witchweapon.wiki/"`) {
		t.Fatal("wiki link was lost")
	}
	if !strings.Contains(html, `role="presentation"`) || !strings.Contains(html, "<!--[if mso]>") || !strings.Contains(html, ">012345</td>") {
		t.Fatal("Outlook layout or complete leading-zero code was lost")
	}
	if emailVerificationSubject != "魔女兵器邮箱验证码" {
		t.Fatal("transactional subject changed")
	}
	for _, removed := range []string{"祈愿塔罗牌", "100 张", "奖励", "免费", "付费", "QQ群", "QQ", "1078249413", "欢迎重逢"} {
		if strings.Contains(plain, removed) || strings.Contains(html, removed) {
			t.Errorf("mail still contains promotional text %q", removed)
		}
	}
	for _, prohibited := range []string{"<script", "<img", "<link", "<style", "@font-face", "@import"} {
		if strings.Contains(strings.ToLower(html), prohibited) {
			t.Errorf("mail contains external resource or active markup %q", prohibited)
		}
	}
}

func TestEmailVerificationTemplateFixedBackgroundAndFallback(t *testing.T) {
	plain, html, err := renderEmailVerification("012345")
	if err != nil {
		t.Fatal(err)
	}
	const background = "https://www.witchweapon.wiki/assets/spring.png"
	for _, required := range []string{`background="` + background + `"`, "background-image:url('" + background + "')", `height="180"`,
		`<v:rect`, `style="width:600px;height:180px;"`, `<v:fill type="frame" src="` + background + `" color="#11131e"`, `</v:textbox></v:rect>`} {
		if !strings.Contains(html, required) {
			t.Errorf("decorative background or Outlook fallback lacks %q", required)
		}
	}
	resources := regexp.MustCompile(`(?:background|src)="([^"]+)"|url\('([^']+)'\)`).FindAllStringSubmatch(html, -1)
	if len(resources) != 3 {
		t.Fatal("unexpected background resource count")
	}
	for _, resource := range resources {
		if resource[1] != background && resource[2] != background {
			t.Fatal("mail background contains another URL or dynamic parameters")
		}
	}
	if !strings.Contains(html, `bgcolor="#11131e" style="padding:18px 20px;background-color:#11131e;"`) ||
		!strings.Contains(html, `bgcolor="#d5bce9"`) {
		t.Fatal("opaque brand backplate or verification card fallback was lost")
	}
	const expectedPlain = "魔女兵器\nWITCH WEAPON / REUNION\n\n您的邮箱验证码：012345\n\n验证码在 30 分钟内有效，请勿向他人透露。\n请返回游戏「设置 → 个人中心」，输入这 6 位验证码，完成当前注册邮箱的验证。\n\n如果这不是您本人的操作，请忽略本邮件。\n魔女兵器 Wiki：https://www.witchweapon.wiki/\n"
	if plain != expectedPlain {
		t.Fatal("decorative HTML background changed the plaintext message")
	}
}

func TestEmailVerificationTemplateEscapesDynamicContent(t *testing.T) {
	unsafe := `<script>alert("test")</script>&<img src=x>`
	plain, html, err := renderEmailVerification(unsafe)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(plain, unsafe) || strings.Contains(html, unsafe) || strings.Contains(html, "<script>") || strings.Contains(html, "<img src=x>") ||
		!strings.Contains(html, "&lt;script&gt;") || !strings.Contains(html, "&amp;") {
		t.Fatal("HTML template did not safely escape dynamic content")
	}
}
