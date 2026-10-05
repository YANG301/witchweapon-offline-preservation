package chat

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"regexp"
	"strings"
	"time"
)

var (
	guildIDPattern      = regexp.MustCompile(`^g[0-9a-f]{24}$`)
	errGuildNotMember   = errors.New("account is not a guild member")
	errGuildUnavailable = errors.New("guild membership is unavailable")
)

type guildMembership struct {
	Version        int    `json:"version"`
	RoleID         string `json:"roleId"`
	GuildID        string `json:"guildId"`
	ConversationID string `json:"conversationId"`
	Privilege      int    `json:"privilege"`
}

type guildMembershipClient struct {
	url    string
	secret string
	http   *http.Client
}

// ConfigureGuildMembership connects this isolated chat process to the Java
// game's authoritative, account-bound membership endpoint. Call before ServeHTTP.
// The endpoint is never selected by an RTM client and must be a numeric loopback
// address; the existing Go-to-Java proxy secret is reused without logging it.
func (s *Server) ConfigureGuildMembership(upstream, secret string) error {
	if s.guildMembership != nil {
		return errors.New("guild membership is already configured")
	}
	if upstream == "" {
		return nil // Rolling upgrade: world chat remains available.
	}
	address, err := netip.ParseAddrPort(upstream)
	if err != nil || !address.Addr().IsLoopback() || address.Port() == 0 ||
		len(secret) < 32 || len(secret) > 256 {
		return errors.New("guild membership requires a numeric loopback host:port and a 32–256 character Java proxy secret")
	}
	transport := &http.Transport{
		Proxy: nil, MaxIdleConns: 32, MaxIdleConnsPerHost: 32,
		IdleConnTimeout: 30 * time.Second,
		DialContext: func(ctx context.Context, network, target string) (net.Conn, error) {
			if target != upstream {
				return nil, errors.New("unexpected guild membership upstream")
			}
			return (&net.Dialer{Timeout: 2 * time.Second}).DialContext(ctx, network, target)
		},
	}
	if err := s.openGuildStore(); err != nil {
		transport.CloseIdleConnections()
		return fmt.Errorf("cannot open guild chat history: %w", err)
	}
	s.guildMembership = &guildMembershipClient{
		url: "http://" + upstream + "/__guild-membership", secret: secret,
		http: &http.Client{Transport: transport, Timeout: 3 * time.Second,
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }},
	}
	return nil
}

func guildConversationID(guildID string) string { return "xinfengzhou-" + guildID }

func isGuildConversationID(cid string) bool {
	return strings.HasPrefix(cid, "xinfengzhou-") &&
		guildIDPattern.MatchString(strings.TrimPrefix(cid, "xinfengzhou-"))
}

func (s *Server) resolveGuildMembership(accountID, roleID string) (guildMembership, error) {
	if s.guildMembership == nil {
		return guildMembership{}, errGuildUnavailable
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, s.guildMembership.url, nil)
	if err != nil {
		return guildMembership{}, errGuildUnavailable
	}
	request.Header.Set("X-WW-Account-ID", accountID)
	request.Header.Set("X-WW-Proxy-Secret", s.guildMembership.secret)
	response, err := s.guildMembership.http.Do(request)
	if err != nil {
		return guildMembership{}, fmt.Errorf("%w: %v", errGuildUnavailable, err)
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusNotFound || response.StatusCode == http.StatusConflict {
		return guildMembership{}, errGuildNotMember
	}
	if response.StatusCode != http.StatusOK {
		return guildMembership{}, errGuildUnavailable
	}
	var member guildMembership
	decoder := json.NewDecoder(io.LimitReader(response.Body, 1025))
	if decoder.Decode(&member) != nil || decoder.Decode(new(any)) != io.EOF ||
		member.Version != 1 || member.RoleID != roleID {
		return guildMembership{}, errGuildUnavailable
	}
	if member.Privilege == -1 && member.GuildID == "" && member.ConversationID == "" {
		return member, errGuildNotMember
	}
	if member.Privilege < 0 || member.Privilege > 2 || !guildIDPattern.MatchString(member.GuildID) ||
		member.ConversationID != guildConversationID(member.GuildID) {
		return guildMembership{}, errGuildUnavailable
	}
	return member, nil
}

func guildAccessError(cmd string, index json.RawMessage, err error) map[string]any {
	if errors.Is(err, errGuildUnavailable) {
		return rtmError(cmd, index, 503, "guild membership unavailable")
	}
	return rtmError(cmd, index, 403, "not a member of this guild")
}
