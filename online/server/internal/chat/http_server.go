package chat

import (
	"net/http"
	"time"
)

// NewHTTPServer is shared by the production chat executable and its WebSocket
// integration tests so their HTTP deadlines cannot silently diverge.
func NewHTTPServer(handler http.Handler) *http.Server {
	return &http.Server{Handler: handler, ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout: 30 * time.Second, WriteTimeout: 35 * time.Second,
		IdleTimeout: 60 * time.Second, MaxHeaderBytes: 8 << 10}
}
