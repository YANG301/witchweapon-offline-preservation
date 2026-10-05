package main

import (
	"embed"
	"net/http"
)

//go:embed admin/index.html admin/style.css admin/app.js admin/data-manager.js admin/mail-center.js admin/server-monitor.js admin/mail_catalog_names.json admin/catalog_metadata.json
var adminAssets embed.FS

func (a *app) mountAdminAssets() {
	a.mux.HandleFunc("GET /admin/", func(w http.ResponseWriter, r *http.Request) {
		if !a.adminRejectUnlessLocal(w, r) || a.admin == nil {
			fail(w, 404, "not_found", "没有找到该页面。")
			return
		}
		var name, contentType string
		switch r.URL.Path {
		case "/admin/":
			name, contentType = "admin/index.html", "text/html; charset=utf-8"
		case "/admin/style.css":
			name, contentType = "admin/style.css", "text/css; charset=utf-8"
		case "/admin/app.js":
			name, contentType = "admin/app.js", "text/javascript; charset=utf-8"
		case "/admin/data-manager.js":
			name, contentType = "admin/data-manager.js", "text/javascript; charset=utf-8"
		case "/admin/mail-center.js":
			name, contentType = "admin/mail-center.js", "text/javascript; charset=utf-8"
		case "/admin/server-monitor.js":
			name, contentType = "admin/server-monitor.js", "text/javascript; charset=utf-8"
		default:
			fail(w, 404, "not_found", "没有找到该页面。")
			return
		}
		if r.URL.RawQuery != "" || r.URL.EscapedPath() != r.URL.Path {
			fail(w, 404, "not_found", "没有找到该页面。")
			return
		}
		content, err := adminAssets.ReadFile(name)
		if err != nil {
			fail(w, 500, "internal_error", "页面暂时不可用。")
			return
		}
		w.Header().Set("Content-Type", contentType)
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(200)
		_, _ = w.Write(content)
	})
}
