package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"math/rand"
	"net"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"crypto/x509"
)

const (
	maxWorkers       = 10_000
	maxBodyBytes     = 64 << 10
	maxLatencySample = 100_000
)

type config struct {
	url             string
	mode            string
	concurrency     int
	users           int
	duration        time.Duration
	requests        int64
	rate            float64
	timeout         time.Duration
	stopErrorRate   float64
	stopAfter       int64
	stopConsecutive int64
}

func defaultConfig() config {
	return config{
		url: "http://127.0.0.1:18080/health", mode: "burst", concurrency: 4,
		users: 4, duration: 10 * time.Second, timeout: 3 * time.Second,
		stopErrorRate: 0.20, stopAfter: 20, stopConsecutive: 20,
	}
}

func parseFlags(args []string) (config, error) {
	c := defaultConfig()
	f := flag.NewFlagSet("loadtest", flag.ContinueOnError)
	f.SetOutput(os.Stderr)
	f.StringVar(&c.url, "url", c.url, "absolute HTTP(S) URL; defaults to local /health")
	f.StringVar(&c.mode, "mode", c.mode, "burst or users")
	f.IntVar(&c.concurrency, "concurrency", c.concurrency, "simultaneous requests in burst mode")
	f.IntVar(&c.users, "users", c.users, "virtual user loops in users mode")
	f.DurationVar(&c.duration, "duration", c.duration, "maximum scheduling time; 0 requires -requests")
	f.Int64Var(&c.requests, "requests", c.requests, "maximum requests; 0 means no request cap")
	f.Float64Var(&c.rate, "rate", c.rate, "aggregate requests per second; required in users mode")
	f.DurationVar(&c.timeout, "timeout", c.timeout, "maximum time for one request")
	f.Float64Var(&c.stopErrorRate, "stop-error-rate", c.stopErrorRate, "stop when overall error ratio reaches this value")
	f.Int64Var(&c.stopAfter, "stop-after", c.stopAfter, "minimum completed requests before error-ratio stop")
	f.Int64Var(&c.stopConsecutive, "stop-consecutive", c.stopConsecutive, "stop after this many consecutive errors")
	if err := f.Parse(args); err != nil {
		return c, err
	}
	if f.NArg() != 0 {
		return c, fmt.Errorf("unexpected positional arguments: %s", strings.Join(f.Args(), " "))
	}
	return c, c.validate()
}

func (c config) validate() error {
	u, err := url.Parse(c.url)
	if err != nil || u == nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || u.User != nil || u.Fragment != "" {
		return errors.New("-url must be an absolute http:// or https:// URL without userinfo or fragment")
	}
	if c.mode != "burst" && c.mode != "users" {
		return errors.New("-mode must be burst or users")
	}
	if c.concurrency < 1 || c.concurrency > maxWorkers || c.users < 1 || c.users > maxWorkers {
		return fmt.Errorf("-concurrency and -users must be between 1 and %d", maxWorkers)
	}
	if c.duration < 0 || c.requests < 0 || (c.duration == 0 && c.requests == 0) {
		return errors.New("set a positive -duration or -requests limit")
	}
	if c.timeout <= 0 || c.timeout > time.Minute {
		return errors.New("-timeout must be > 0 and <= 1m")
	}
	if math.IsNaN(c.rate) || math.IsInf(c.rate, 0) || c.rate < 0 || c.rate > 1_000_000 {
		return errors.New("-rate must be between 0 and 1,000,000 requests/s")
	}
	if c.mode == "users" && c.rate <= 0 {
		return errors.New("-mode users requires -rate > 0")
	}
	if c.rate > 0 && time.Duration(float64(time.Second)/c.rate) <= 0 {
		return errors.New("-rate exceeds timer resolution")
	}
	if c.mode == "users" && float64(c.users)/c.rate > float64(math.MaxInt64)/float64(time.Second) {
		return errors.New("virtual user interval is too long")
	}
	if math.IsNaN(c.stopErrorRate) || c.stopErrorRate <= 0 || c.stopErrorRate > 1 {
		return errors.New("-stop-error-rate must be in (0, 1]")
	}
	if c.stopAfter < 1 || c.stopConsecutive < 1 {
		return errors.New("-stop-after and -stop-consecutive must be positive")
	}
	return nil
}

type result struct {
	workerID   int
	statusCode int
	latency    time.Duration
	errType    string
}

type summary struct {
	mode              string
	configuredWorkers int
	activeWorkers     int
	rateLimit         float64
	elapsed           time.Duration
	completed         int64
	succeeded         int64
	failed            int64
	statusCodes       map[int]int64
	networkErrors     map[string]int64
	p50, p95, p99     time.Duration
	maxLatency        time.Duration
	latencySamples    int
	stopReason        string
}

func classifyError(err error) string {
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, os.ErrDeadlineExceeded) {
		return "timeout"
	}
	var dnsErr *net.DNSError
	if errors.As(err, &dnsErr) {
		return "dns"
	}
	var certUnknown x509.UnknownAuthorityError
	var certInvalid x509.CertificateInvalidError
	var certHost x509.HostnameError
	if errors.As(err, &certUnknown) || errors.As(err, &certInvalid) || errors.As(err, &certHost) {
		return "tls_certificate"
	}
	if errors.Is(err, syscall.ECONNREFUSED) {
		return "connection_refused"
	}
	if errors.Is(err, syscall.ECONNRESET) || errors.Is(err, syscall.EPIPE) {
		return "connection_reset"
	}
	if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
		return "eof"
	}
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return "timeout"
	}
	var opErr *net.OpError
	if errors.As(err, &opErr) {
		return "network_" + opErr.Op
	}
	return "other"
}

func requestOnce(parent context.Context, client *http.Client, target string, timeout time.Duration, workerID int) result {
	started := time.Now()
	r := result{workerID: workerID}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		r.errType = "request_build"
		r.latency = time.Since(started)
		return r
	}
	req.Header.Set("User-Agent", "witchweapon-loadtest/1")
	resp, err := client.Do(req)
	if err != nil {
		r.errType = classifyError(err)
		r.latency = time.Since(started)
		return r
	}
	defer resp.Body.Close()
	r.statusCode = resp.StatusCode
	n, readErr := io.Copy(io.Discard, io.LimitReader(resp.Body, maxBodyBytes+1))
	if readErr != nil {
		r.errType = classifyError(readErr)
	} else if n > maxBodyBytes {
		r.errType = "body_limit"
	}
	r.latency = time.Since(started)
	return r
}

func waitUntil(parent context.Context, stop <-chan struct{}, when time.Time) bool {
	delay := time.Until(when)
	if delay <= 0 {
		select {
		case <-parent.Done():
			return false
		case <-stop:
			return false
		default:
			return true
		}
	}
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-parent.Done():
		return false
	case <-stop:
		return false
	case <-timer.C:
		return true
	}
}

func run(parent context.Context, c config) (summary, error) {
	if err := c.validate(); err != nil {
		return summary{}, err
	}
	workers := c.concurrency
	if c.mode == "users" {
		workers = c.users
	}
	transport := &http.Transport{
		// Measure the named server directly instead of an incidental system proxy.
		Proxy:        nil,
		MaxIdleConns: workers * 2, MaxIdleConnsPerHost: workers,
		MaxConnsPerHost: workers, IdleConnTimeout: 90 * time.Second,
		TLSHandshakeTimeout: c.timeout, ResponseHeaderTimeout: c.timeout,
		ForceAttemptHTTP2: true,
	}
	defer transport.CloseIdleConnections()
	client := &http.Client{
		Transport: transport, Timeout: c.timeout,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse },
	}
	started := time.Now()
	stop := make(chan struct{})
	var stopOnce sync.Once
	var stopReason atomic.Value
	stopRun := func(reason string) {
		stopOnce.Do(func() { stopReason.Store(reason); close(stop) })
	}
	if c.duration > 0 {
		timer := time.AfterFunc(c.duration, func() { stopRun("duration") })
		defer timer.Stop()
	}
	var ticker *time.Ticker
	if c.mode == "burst" && c.rate > 0 {
		ticker = time.NewTicker(time.Duration(float64(time.Second) / c.rate))
		defer ticker.Stop()
	}
	results := make(chan result, min(workers*2, 16_384))
	var tickets atomic.Int64
	var wg sync.WaitGroup
	for id := 0; id < workers; id++ {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()
			var next time.Time
			var interval time.Duration
			if c.mode == "users" {
				interval = time.Duration(float64(time.Second) * float64(c.users) / c.rate)
				next = started.Add(time.Duration(float64(time.Second) * float64(workerID) / c.rate))
			}
			for {
				if c.mode == "users" {
					if !waitUntil(parent, stop, next) {
						return
					}
				} else if ticker != nil {
					select {
					case <-parent.Done():
						return
					case <-stop:
						return
					case <-ticker.C:
					}
				} else if !waitUntil(parent, stop, time.Time{}) {
					return
				}
				if c.requests > 0 {
					ticket := tickets.Add(1)
					if ticket > c.requests {
						return
					}
					// Wake sleeping users after reserving the last request.
					// Already reserved requests still run, preserving the exact cap.
					if ticket == c.requests {
						stopRun("requests")
					}
				}
				results <- requestOnce(parent, client, c.url, c.timeout, workerID)
				if c.mode == "users" {
					next = next.Add(interval)
					if time.Now().After(next) {
						next = time.Now().Add(interval)
					}
				}
			}
		}(id)
	}
	go func() { wg.Wait(); close(results) }()
	s := summary{
		mode: c.mode, configuredWorkers: workers, rateLimit: c.rate,
		statusCodes: make(map[int]int64), networkErrors: make(map[string]int64),
	}
	active := make(map[int]struct{}, workers)
	latencies := make([]time.Duration, 0, min(maxLatencySample, 1024))
	rng := rand.New(rand.NewSource(time.Now().UnixNano()))
	var consecutive int64
	for r := range results {
		active[r.workerID] = struct{}{}
		s.completed++
		if r.statusCode != 0 {
			s.statusCodes[r.statusCode]++
		}
		if r.errType != "" {
			s.networkErrors[r.errType]++
		}
		if r.errType == "" && r.statusCode >= 200 && r.statusCode < 300 {
			s.succeeded++
			consecutive = 0
		} else {
			s.failed++
			consecutive++
		}
		if r.latency > s.maxLatency {
			s.maxLatency = r.latency
		}
		if len(latencies) < maxLatencySample {
			latencies = append(latencies, r.latency)
		} else if pick := rng.Int63n(s.completed); pick < maxLatencySample {
			latencies[pick] = r.latency
		}
		if s.completed >= c.stopAfter && float64(s.failed)/float64(s.completed) >= c.stopErrorRate {
			stopRun("error-rate")
		}
		if consecutive >= c.stopConsecutive {
			stopRun("consecutive-errors")
		}
	}
	s.activeWorkers = len(active)
	s.elapsed = time.Since(started)
	if v := stopReason.Load(); v != nil {
		s.stopReason = v.(string)
	}
	if s.stopReason == "" {
		if parent.Err() != nil {
			s.stopReason = "cancelled"
		} else {
			s.stopReason = "requests"
		}
	}
	s.latencySamples = len(latencies)
	if len(latencies) > 0 {
		sort.Slice(latencies, func(i, j int) bool { return latencies[i] < latencies[j] })
		quantile := func(p float64) time.Duration {
			return latencies[int(math.Ceil(p*float64(len(latencies))))-1]
		}
		s.p50, s.p95, s.p99 = quantile(0.50), quantile(0.95), quantile(0.99)
	}
	return s, nil
}

func printSummary(w io.Writer, s summary) {
	fmt.Fprintf(w, "mode=%s workers=%d active_workers=%d rate_limit=%.2f/s\n", s.mode, s.configuredWorkers, s.activeWorkers, s.rateLimit)
	fmt.Fprintf(w, "elapsed=%s stop_reason=%s completed=%d success=%d errors=%d actual_rps=%.2f\n",
		s.elapsed.Round(time.Millisecond), s.stopReason, s.completed, s.succeeded, s.failed,
		float64(s.completed)/s.elapsed.Seconds())
	keys := make([]int, 0, len(s.statusCodes))
	for k := range s.statusCodes {
		keys = append(keys, k)
	}
	sort.Ints(keys)
	fmt.Fprint(w, "status_codes:")
	for _, k := range keys {
		fmt.Fprintf(w, " %d=%d", k, s.statusCodes[k])
	}
	fmt.Fprintln(w)
	errKeys := make([]string, 0, len(s.networkErrors))
	for k := range s.networkErrors {
		errKeys = append(errKeys, k)
	}
	sort.Strings(errKeys)
	fmt.Fprint(w, "network_or_body_errors:")
	for _, k := range errKeys {
		fmt.Fprintf(w, " %s=%d", k, s.networkErrors[k])
	}
	fmt.Fprintln(w)
	fmt.Fprintf(w, "latency_p50=%s p95=%s p99=%s max=%s samples=%d\n",
		s.p50.Round(time.Microsecond), s.p95.Round(time.Microsecond), s.p99.Round(time.Microsecond),
		s.maxLatency.Round(time.Microsecond), s.latencySamples)
	fmt.Fprintln(w, "Note: GET endpoint throughput is not an estimate of concurrently online game players.")
}

func main() {
	c, err := parseFlags(os.Args[1:])
	if err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return
		}
		fmt.Fprintln(os.Stderr, "loadtest:", err)
		os.Exit(2)
	}
	s, err := run(context.Background(), c)
	if err != nil {
		fmt.Fprintln(os.Stderr, "loadtest:", err)
		os.Exit(2)
	}
	printSummary(os.Stdout, s)
	if s.failed > 0 {
		os.Exit(1)
	}
}
