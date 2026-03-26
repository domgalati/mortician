## Summary

At **17:42 UTC**, mobile checkout requests began failing globally due to a CDN rule drift that replayed stale deny responses for authenticated mobile sessions.  
Web checkout remained mostly healthy, which made this a high-severity but path-specific outage.

The incident was declared within one minute, rollback started at 17:48 UTC, and full recovery was confirmed at 17:50 UTC.

## Impact & Severity

### Affected Services

- `mobile-checkout` user flow (iOS + Android)
- `cdn-edge` rule engine (`mobile_checkout_v2`)
- `checkout-api` elevated `EDGE_DENIAL` responses

### Duration of Outage

`8 minutes` (17:42 UTC to 17:50 UTC)

### Business Impact

| Metric | Value | Note |
|---|---:|---|
| Mobile checkout success rate | 98.9% -> 22.4% | At peak degradation |
| Failed transactions | 5,119 | During incident window |
| Estimated revenue at risk | $301,000 | Gross estimate |
| Support tickets/chats | 181 | 73% mobile-only |

**Severity:** `SEV-1` (global checkout path degraded for mobile customers).

## Root Cause

The #1 CDN rule `mobile_checkout_v2` was promoted with an unintended cache-key change that omitted an auth-scoping header for a subset of mobile requests.  
As a result, deny responses were cached and replayed across sessions.

### Trigger chain

1. Rule deploy altered cache key behavior
2. Stale deny responses became cache hits
3. `checkout-api` surfaced `EDGE_DENIAL` errors
4. Mobile conversion dropped sharply

### Why detection took a few minutes

- Primary alert tracked blended checkout SLO, not mobile path independently
- Rule validation did not include auth-scoped cache-key linting
- Staging traffic did not reproduce production session diversity

### Evidence

```text
2026-03-24T17:42:03.412Z edge-iad-1 ERROR upstream_denied route=/mobile/checkout cache_status=HIT policy=deny_stale
2026-03-24T17:43:14.713Z checkout-api ERROR checkout submit failed code=EDGE_DENIAL trace_id=9f11f66a74
```


![Request flow with failing edge node](/api/postmortems/cdnburn/assets/request-flow.svg)

![Request flow with failing edge node](/api/postmortems/cdnburn/assets/traffic-drop.svg)

## Resolution

### Temporary

- Reverted CDN rule to previous known-good revision
- Issued global edge cache purge
- Raised status-page updates every 3 minutes until mobile success rate stabilized

### Permanent

- Add CI lint checks for auth-sensitive cache-key fields
- Build mobile-path SLO alerting independent of blended checkout SLO
- Introduce "safe-mode publish" requiring canary validation before global rollout
- Run quarterly game day for edge rollback + purge procedure
