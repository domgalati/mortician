## Summary

Starting around **18:18 UTC**, users in one region reported slower-than-normal login completion times.
Authentication remains available and successful, but latency is intermittently elevated.

This incident is **ongoing** and currently tracked as a minor impact while investigation continues.

## Impact & Severity

### Affected Services

- `auth-api` login endpoint
- `session-issuer` token mint path

### Duration of Outage

No hard outage at this time. Degraded performance has been observed for ~15 minutes and is ongoing.

### Business Impact

- No complete login failure observed
- Regional p95 login latency increased from ~420ms to ~1.8s
- Mild increase in support chat volume ("login feels slow")

## Root Cause

Investigation in progress.

Current hypothesis:

1. bursty cache misses in session profile lookups
2. increased read load on one replica
3. occasional tail-latency spikes in token issuance flow

Preliminary log signal:

```text
2026-03-24T18:20:11.644Z auth-api WARN login latency elevated region=us-west p95_ms=1820 cache_miss_ratio=0.37
```

## Resolution

### Temporary

- Enabled additional cache warming for top active user segments
- Shifted 15% read traffic to secondary replica pool

### Permanent

Pending investigation outcome.
