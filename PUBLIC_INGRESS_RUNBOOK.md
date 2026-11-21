# Ubuntu direct deployment ingress

## URL ownership

`DEPLOY_PUBLIC_BASE_URL` is the base URL returned to users for deployed
repositories. It is **not** the CICD-Engine API or backend API.

The retired `api.pwd.kr` name is not used by this configuration. The current
user-facing URL rule is:

```text
https://112.186.136.153/services/{githubOwner}/{repository}
```

The engine reaches its backend privately at `http://backend:8000` on the
`capstone-internal` Docker network. A LAN client that explicitly needs the
backend uses `http://192.168.0.4:8000`.

## Architecture

```text
Internet TCP 80/443
  -> ipTIME NAT: 112.186.136.153 -> 192.168.0.4
  -> capstone-public-ingress (Caddy, Compose)
  -> capstone-deploy-router:80 (Nginx, Compose)
  -> one independent app container per repository
```

Caddy forwards the original URI path and query string unchanged to the
deployment router, handles WebSocket upgrades, and supplies `Host`,
`X-Real-IP`, and `X-Forwarded-*`. The inner router removes only the routing
prefix (`/services/{owner}/{repo}`) before calling the selected application.

Application host ports in `10000-19999` bind to `127.0.0.1`, not `0.0.0.0`.
They remain useful for host-local diagnostics but cannot be reached from the
LAN or Internet. Caddy and the router reach applications over the private
Docker network.

## Network assessment (2026-08-11 KST)

- Ubuntu address: `192.168.0.4/24`, assigned by DHCP.
- Default gateway: `192.168.0.1` (ipTIME).
- Public IPv4: two independent checks returned `112.186.136.153`.
- First hop after the router: public address `112.186.136.1`.
- The ipTIME WAN API reports `112.186.136.153` as its own WAN address.
- Conclusion: this is definitively not a CGNAT/private upstream assignment.
  Direct inbound NAT is the appropriate design.
- Static/dynamic status: a snapshot cannot prove a static ISP assignment.
  Unless the ISP contract explicitly guarantees a static address, treat it as
  dynamic. Reserve `192.168.0.4` for this Ubuntu machine in ipTIME DHCP and
  update `.env` plus Caddy whenever the public IP changes.
- `api.pwd.kr` still resolved to the former EC2 address `54.221.222.244` at the
  time of assessment. It is intentionally outside this new URL path and its DNS
  record may be deleted at the DNS provider.

## One-time ipTIME settings

TCP 80 and 443 were added through the router's UPnP API during the migration.
Both entries currently map to `192.168.0.4` with an indefinite lease and were
read back successfully. For router-reboot durability, mirror them as static
rules in the web UI:

Open `http://192.168.0.1`, then use **Advanced Settings -> NAT/Router
Management -> Port Forwarding** (wording varies by firmware):

| Name | Protocol | External port | Internal address | Internal port |
| --- | --- | ---: | --- | ---: |
| cicd-http | TCP | 80 | 192.168.0.4 | 80 |
| cicd-https | TCP | 443 | 192.168.0.4 | 443 |

Also add a DHCP reservation that maps this server's NIC/MAC to
`192.168.0.4`. Do not forward `8000`, `19080`, or `10000-19999`.

Before changing NAT, confirm that the router's WAN status page shows
`112.186.136.153`. If it instead shows an RFC1918 address or
`100.64.0.0/10`, direct inbound access is not possible and the Cloudflare
fallback below is required.

## Host and Compose activation

TCP 80 was occupied only by Ubuntu's Apache default site during assessment.
Apply the checked-in host preparation script, then start Caddy:

```bash
cd /home/capstone/CICD-Engine
sudo ./scripts/configure-direct-ingress-host.sh
docker compose config --quiet
docker compose up -d public-ingress
docker compose -f deployments/compose.yaml up -d
```

If UFW is active, the script allows TCP 80/443 and denies TCP
`10000:19999`. It deliberately does not enable an inactive firewall, because
blindly enabling UFW could lock out SSH. Loopback-only Docker bindings protect
the application range in either case.

The Caddy `caddy_data` and `caddy_config` named volumes retain ACME account and
certificate state. Every service uses `restart: unless-stopped`; Docker is
enabled at boot on this host. These settings restore ingress and deployed apps
after a reboot.

## HTTPS behavior

Let's Encrypt now issues publicly trusted IPv4 certificates. IP certificates
must use the `shortlived` profile and are valid for about 160 hours. Caddy
2.11.4 is configured with that profile and renews automatically. Successful
issuance requires inbound TCP 80 or 443 to reach Caddy, so NAT must be active.

The production ACME endpoint is configured. Keep both Caddy volumes; deleting
them discards renewal state and risks rate-limit problems.

Because TLS clients do not normally send an SNI value for an IP literal, the
Caddy global `default_sni` is set to `112.186.136.153`. Without that setting the
certificate can be issued correctly but not selected during a normal IP-based
TLS handshake.

## Verification and AWS retirement

Run the following from a genuinely external network, such as a laptop tethered
to a mobile phone (a LAN hairpin test is not sufficient):

```bash
curl -i https://112.186.136.153/services/NekoNyangYee/Samplejavascript4/
curl -i https://112.186.136.153/services/NekoNyangYee/Samplejavascript4/health
./scripts/verify-direct-ingress.sh 112.186.136.153
```

The current Samplejavascript4 image returns `200 {"ok":true}` for `/health`.
Its own `/` handler currently returns `404 {"error":"not_found"}`; the
`X-CICD-Service` response header confirms that this response came through the
correct deployment route. A `200` root response requires an application route,
not a proxy change.

Only after the external HTTPS checks pass:

```bash
docker rm -f capstone-deploy-tunnel
```

The tunnel service and its image build have already been removed from the main
Compose definition, so the container cannot return on the next Compose
reconciliation. After stopping the EC2 instance, repeat both external URLs.
Then remove the former EC2 Nginx ingress/SSM resources and the local tunnel SSH
key/known-host files according to the AWS account's retention policy.

## Completed migration result (2026-08-11 KST)

- Let’s Encrypt production IP certificate issued successfully. Its first
  validity window is `2026-08-11 12:18:52Z` through
  `2026-08-18 04:18:51Z`; Caddy renewal state is persisted in
  `capstone-caddy-data`.
- `GET /services/NekoNyangYee/Samplejavascript4/health?probe=public-ip`
  returned HTTP/2 `200 {"ok":true}` through Caddy and the deployment router.
- `GET /services/NekoNyangYee/quiz-web/` returned HTTP/2 `200`, proving that
  two independent Compose applications use the same path rule concurrently.
- HTTP port 80 returns a `308` redirect to the same path on HTTPS.
- `openssl s_client -verify_ip 112.186.136.153` returned verification code 0.
- Caddy, the router, Samplejavascript4, and the engine were restarted together;
  HTTPS recovered and all have `restart: unless-stopped`.
- Docker is enabled and active at boot; Apache is disabled.
- Application ports `17397` and `18139` plus router port `19080` listen only on
  `127.0.0.1`; public ingress listens on TCP 80/443.
- The reverse SSH container was removed, its three dedicated SSH key/host files
  were permanently deleted, and AWS instance `i-0bbbac93709a304fb` was stopped.
  The public-IP health URL remained HTTP/2 200 afterward.
- UFW was inactive and was intentionally not enabled. WAN exposure is limited
  by the two ipTIME port mappings, while direct application exposure is blocked
  structurally by loopback-only Docker bindings.

## CGNAT fallback

Cloudflare Tunnel is only needed if the router WAN address is private/CGNAT or
the ISP blocks inbound TCP 80/443. A stable Cloudflare Tunnel requires a domain
managed in Cloudflare; it cannot publish a durable HTTPS service at this raw
public IP. If that condition appears later, assign a hostname, run
`cloudflared` on `capstone-internal`, route the hostname to
`http://capstone-deploy-router:80`, and set `DEPLOY_PUBLIC_BASE_URL` to that
hostname plus `/services`. Do not restore AWS, SSM, or reverse SSH.

## Security policy 1.4.0 deployment (2026-11-15)

- Engine: `capstone-engine:policy-1.4.0`; backend: `capstone-back:policy-1.4.0`.
- Images extend the previously deployed `selected-policy-20261115` images and replace only `app/security_policy.py`, `app/orchestrator.py` (engine), `app/main.py`, and `app/api/approvals_router.py` (backend).
- Existing pipeline processes finished before replacement. Container environment, network aliases, ports, bind mounts and restart policies were preserved.
- Previous stopped containers are retained as `capstone-cicd-engine-before-policy-140` and `capstone-back-before-policy-140` for rollback. Do not start these alongside the current containers: the engine could claim jobs and the backend uses the same port.
- Verified public HTTPS `/health`, running engine policy version `1.4.0`, and backend Medium approval support.
- Desktop renderer changes: Capstone-FE commit `97bc69f`, version `1.6.2`. The desktop release workflow builds Windows and macOS installers. Installed clients must update to receive the changed policy table and Medium approval controls.

## Callback latency optimization (2026-11-15)

Backend image `capstone-back:policy-1.4.0-fast-events` adds batched event sequence allocation and inserts canonical/compatibility events together. It also reuses the callback job lookup for the terminal-status check. Durable ordering, transaction locks, idempotency and synchronous stage-start persistence remain enabled. No client update or schema migration is required.

Validation: 43 PostgreSQL/stream/approval tests passed against a disposable local DB. With the measured 194 ms production DB round-trip delay simulated per statement, 50-line event persistence changed from 54 statements / 10.85 s to 4 statements / 0.80 s; a stage-completed event changed from 8 statements / 1.58 s to 4 statements / 0.79 s. These are event persistence benchmarks, not full pipeline timings. Previous backend retained as `capstone-back-before-fast-events`.

## Faster stage updates (2026-11-15)

- Engine image: `capstone-engine:policy-1.4.0-fast-stage`, based on the existing policy 1.4.0 image with `app/callback.py` replaced. HTTPX 0.28.1 is already present and now explicitly pinned in requirements.
- Callback connections are reused in independent per-thread pools for stage persistence and live logs. Existing acknowledgement-before-execution behavior and retries remain. Redirects are not followed with callback credentials.
- `POLL_INTERVAL_SEC=5` in the running engine and local Compose configuration, down from 15 seconds. This reduces job pickup delay; it does not promise a five-second total startup time.
- Previous engine retained as `capstone-cicd-engine-before-fast-stage`. No active pipelines were interrupted.
- Desktop v1.6.3, commit `623d73e`, applies persisted stage event payloads directly, guards against stale REST responses, uses ten-second reconciliation while the WebSocket is live and removes delayed untagged-log reveal bookkeeping. REST fallback remains at 2.5 seconds when the stream is disconnected.
- Validation: 30 engine tests and 30 desktop tests passed; TypeScript/Vite build passed. Live engine made three backend health requests over one retained connection. Public HTTPS health and security policy 1.4.0 verified. End-to-end pipeline speedup is workload dependent and was not benchmarked by starting a user deployment.

## Faster pipeline start acknowledgement (2026-11-15)

Backend image `capstone-back:policy-1.4.0-fast-start` changes only `app/main.py` on top of `policy-1.4.0-fast-events`. `/api/pipelines` now reuses the request/authentication DB session, performs conflict check and insertion in one transaction, and creates the initial stage plan without querying a newly created job or updating its counter again. A repository/branch transaction lock prevents concurrent duplicate submissions. Success is still returned only after job and stages commit; failures roll back before any in-memory acknowledgement.

Validation: 42 tests passed against a disposable PostgreSQL database, including first full scan, subsequent selected scans, concurrent starts, commit failure rollback, one-session HTTP dependency reuse, custom workflows, realtime replay and approvals. A controlled benchmark with 194 ms per SQL statement showed 6 to 5 statements, 1 to 0 extra DB connections, and 1.28 s to 1.04 s for start processing. These are simulated DB-delay measurements, not a browser or production end-to-end SLA. Frontend update is unnecessary. Previous backend retained as `capstone-back-before-fast-start`.
