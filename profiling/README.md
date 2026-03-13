# ThingsBoard VisualVM Profiling Setup Guide

Complete step-by-step guide for TP2 profiling assignment.

**Hardware Target**: Ryzen 9 4900HS (35W TDP), 16GB RAM, Windows (WSL2 Docker backend)
**Setup**: Docker + PostgreSQL

---

## Quick Start Checklist

- [ ] All Docker files converted to LF line endings (no CRLF)
- [ ] JMX enabled for tb-core1 in `docker/docker-compose.yml` (port 9011)
- [ ] Memory budget fits 16GB RAM (`-Xmx1024M` shared, `-Xmx2048M` for tb-core1)
- [ ] Docker containers running
- [ ] VisualVM installed and connected to `localhost:9011`
- [ ] Python environment setup
- [ ] 50 test devices created
- [ ] Ready to run scenarios

---

## Phase 1: Install & Configure ThingsBoard

### Step 1.1: Fix Line Endings (CRITICAL on Windows)

All `.sh`, `.conf`, `.env`, and `.cfg` files under `docker/` must use **Unix LF** line endings, not Windows CRLF. This has already been fixed. If you re-clone or modify files, verify with:

```powershell
# In PowerShell, from the project root:
Get-ChildItem docker -Recurse -Include "*.sh","*.conf","*.env","*.cfg" | ForEach-Object {
    $c = [System.IO.File]::ReadAllText($_.FullName)
    if ($c -match "`r`n") { Write-Host "CRLF: $($_.Name)" }
}
```

To fix any remaining CRLF files: open in VS Code → click **CRLF** in bottom-right status bar → select **LF** → save.

### Step 1.2: Verify Configuration Files

**1. `docker/.env`** — Shared JVM options (no JMX here — it's per-service):

```bash
JAVA_OPTS="-Xmx1024M -Xms512M -Xss384k -XX:+AlwaysPreTouch"
```

**2. `docker/docker-compose.yml`** — tb-core1 overrides JAVA_OPTS to add JMX on port 9011:

```yaml
tb-core1:
  environment:
    JAVA_OPTS: "${JAVA_OPTS} -Xmx2048M -Dcom.sun.management.jmxremote -Dcom.sun.management.jmxremote.port=9011 -Dcom.sun.management.jmxremote.rmi.port=9011 ..."
  ports:
    - "9011:9011" # JMX exposed directly (bypasses HAProxy)
```

**Why this design**: JMX uses Java RMI which does a two-phase connection. The RMI callback advertises the container-internal port, so the internal port must equal the external port (9011=9011). HAProxy TCP proxy cannot handle this reliably, so we expose JMX directly from the container.

**Memory budget** (fits 16GB RAM with WSL2):

- tb-core1: 2048MB max (profiled node — gets extra heap)
- All other Java services: 1024MB max, 512MB initial
- PostgreSQL, Kafka, Zookeeper, Valkey, HAProxy: ~2-3GB
- Total at idle: ~5-6GB; at peak: ~13GB

### Step 1.3: Install ThingsBoard (Git Bash)

```bash
cd docker
bash docker-install-tb.sh --loadDemo
```

**Expected**: Database initialization logs, demo data loading. Wait for completion.

**If you see errors**:

- `$'\r': command not found` → CRLF line endings not fixed (Step 1.1)
- `Invalid -Xlog option` → CRLF in `thingsboard.conf` garbles the JVM flags

### Step 1.4: Start ThingsBoard

```bash
bash docker-start-services.sh
```

**Wait 3-5 minutes** for all services to start.

Verify all containers are running:

```bash
docker ps
```

Should show 15+ containers including `tb-core1`, `tb-core2`, `tb-rule-engine1/2`, `postgres`, `kafka`, `zookeeper`, `haproxy-certbot`, etc.

### Step 1.5: Verify Installation

1. Open browser: http://localhost
2. Login: `tenant@thingsboard.org` / `tenant`
3. Should see ThingsBoard dashboard

---

## Phase 2: Setup VisualVM

### Step 2.1: Download VisualVM

1. Download from: https://visualvm.github.io/download.html
2. Extract (e.g., to `C:\VisualVM`)

### Step 2.2: Launch VisualVM

```powershell
C:\VisualVM\bin\visualvm.exe
```

### Step 2.3: Add JMX Connection

1. **File → Add JMX Connection**
2. Enter connection details:
   - Connection: `localhost:9011`
   - Display name: `ThingsBoard Core 1`
   - **Uncheck** "Use security credentials"
   - **Check** "Do not require SSL connection"
3. Click **OK**

### Step 2.4: Connect to ThingsBoard

1. In left panel, expand **JMX**
2. Double-click **localhost:9011**
3. Available tabs: **Overview, Monitor, Threads, Sampler**

**Success indicator**: Monitor tab shows CPU and Heap graphs updating in real-time.

> **Note**: Over remote JMX, only the **Sampler** tab is available for CPU/Memory profiling (not the Profiler tab, which requires local JVM attachment). The Sampler is sufficient — it provides hot spot analysis with method-level self-time percentages.

---

## Phase 3: Setup Python Environment (Locust)

### Step 3.1: Create Virtual Environment

```bash
cd profiling
python -m venv venv
venv\Scripts\activate  # On Windows
```

### Step 3.2: Install Dependencies

```bash
pip install -r requirements.txt
```

Packages: `locust` (load testing framework), `websocket-client` (gevent-compatible WebSocket), `requests`.

### Step 3.3: Create Test Devices

```bash
python setup_devices.py 50
```

Verify: ThingsBoard UI → Devices page → should see `LoadTestDevice1` through `LoadTestDevice50`.

### Step 3.4: Verify Locust Installation

```bash
locust --version
```

Should print `locust 2.x.x`.

---

## Phase 4: Run Profiling Scenarios (Locust)

All scenarios live in a single `locustfile.py` with three User classes. You select which scenario to run via the CLI or the Locust web UI class picker.

### General Workflow

1. **Start VisualVM** and connect to `localhost:9011`
2. **Start Locust** targeting one scenario
3. **Ramp users** — either from the web UI or `--headless` CLI flags
4. **Collect data** in VisualVM while Locust runs
5. **Export reports** — Locust auto-generates HTML + CSV

### How to Launch Locust

**With web UI** (recommended — lets you control ramp-up interactively):

```bash
cd profiling
locust -f locustfile.py --class-picker
```

Open http://localhost:8089 in your browser. Select the User class for the scenario you want.

**Headless with HTML report**:

```bash
locust -f locustfile.py <UserClass> --headless -u <users> -r <spawn_rate> -t <duration> \
    --html reports/<scenario>.html --csv reports/<scenario>
```

> Create the `reports/` directory first: `mkdir reports`

---

### SCENARIO 1: Progressive WebSocket Load (MANDATORY)

**User class**: `WebSocketUser`
**What it tests**: WebSocket connection handling, concurrent sessions, memory retention
**Assignment targets**: Q3.1 (CPU), Q3.2 (Memory/Heap), Q3.3 (Energy), Q3.4 (Visualization), Breaking point

#### VisualVM Preparation:

1. Connect to `localhost:9011`
2. Go to **Monitor** tab — keep visible for CPU% and Heap graphs
3. Go to **Sampler** tab → Click **CPU** button to start sampling

#### Execute Test:

**Option A — Web UI (recommended for staged ramp-up):**

```bash
locust -f locustfile.py WebSocketUser
```

Open http://localhost:8089. Start with 10 users (spawn rate 5), then use **Edit** to ramp to 25, 50, 75, 100, 150. Hold each stage ~60 seconds and take VisualVM snapshots.

**Option B — Headless (single ramp):**

```bash
locust -f locustfile.py WebSocketUser --headless -u 150 -r 10 -t 6m \
    --html reports/scenario1.html --csv reports/scenario1
```

#### Data Collection at EACH Stage:

1. **Sampler tab**: Click **Snapshot** button (camera icon) → saves CPU hot spots
2. **Monitor tab**: Note Heap used (MB) and CPU %
3. **Threads tab**: Count threads in RUNNABLE state
4. **Screenshot** each tab
5. **Locust web UI**: Screenshot the Charts tab (RPS, response times, failures)

Save VisualVM snapshots: File → Save As → `scenario1_Nusers_snapshot.nps`

#### Locust Metrics to Record:

| Metric                           | Where in Locust UI          |
| -------------------------------- | --------------------------- |
| Requests/sec                     | Charts tab                  |
| Response time (median, p95, p99) | Statistics tab              |
| Failure rate                     | Charts tab / Statistics tab |
| Active users                     | Charts tab                  |

#### What to Look For (CPU — Q3.1):

- Hot methods at each load level: `NioEventLoop.run()`, `DefaultWebSocketService.sendUpdate()`, Netty channel handlers
- How CPU% scales with concurrent users

#### What to Look For (Memory — Q3.2):

- Heap growth pattern as users increase
- After a stage completes: do WebSocket session objects get cleaned up?
- Force GC (Monitor tab → "Perform GC" button) and check if heap drops

#### Breaking Point:

- Locust failure rate spikes (visible in Charts tab)
- WebSocket disconnections (check `connect+subscribe` failures)
- Heap stays at max (2048MB) — no GC recovery
- CPU sustained > 90%

---

### SCENARIO 2: Telemetry Ingestion Load

**User class**: `TelemetryUser`
**What it tests**: HTTP REST telemetry pipeline, JSON parsing, database writes
**Architecture**: Telemetry → tb-http-transport → Kafka → tb-rule-engine → PostgreSQL. tb-core1 handles subscription updates.

#### VisualVM Preparation:

1. Go to **Sampler** tab → Click **CPU** button to start CPU sampling
2. Keep **Monitor** tab visible

#### Execute Test:

```bash
locust -f locustfile.py TelemetryUser --headless -u 30 -r 10 -t 2m \
    --html reports/scenario2.html --csv reports/scenario2
```

With `wait_time = between(0.1, 0.5)`, 30 users produce ~100-300 msg/sec.

For higher throughput, increase users:

```bash
locust -f locustfile.py TelemetryUser --headless -u 100 -r 20 -t 2m \
    --html reports/scenario2_high.html --csv reports/scenario2_high
```

#### Data Collection:

**During test** — Locust prints a summary table every 10 seconds showing:

- Requests/sec, median/avg/p95 response times, failure count

**After test**:

1. **Sampler tab**: Click **Snapshot** button
2. In snapshot → **Hot Spots** tab → sort by **Self Time %**
3. Screenshot top 10 methods
4. **Open** `reports/scenario2.html` for the full Locust report with response time charts

**Expected hot spots on tb-core1**:

- Kafka consumer threads processing subscription updates
- `com.fasterxml.jackson.databind.*` (JSON parsing)
- `org.thingsboard.server.service.telemetry.*`
- Thread waits on HikariCP (database connection pool)

---

### SCENARIO 3: Admin REST API Burst

**User class**: `AdminUser`
**What it tests**: Thread pools, DB connection pooling, REST API resilience under concurrent load

#### VisualVM Preparation:

1. Go to **Sampler** tab → Click **CPU** button (for CPU sampling)
2. Also go to **Sampler** → Click **Memory** button (for memory sampling)
3. Keep **Threads** tab visible

#### Execute Test:

```bash
locust -f locustfile.py AdminUser --headless -u 60 -r 15 -t 2m \
    --html reports/scenario3.html --csv reports/scenario3
```

60 users = ~40 slow-polling + 20 rapid-burst equivalent (weighted tasks distribute the load).

#### Data Collection:

**During test**:

- **Threads tab**: Look for threads in BLOCKED/WAITING state (indicates contention)
- **Monitor tab**: Watch CPU% and Heap during burst
- **Locust console**: Watch per-endpoint RPS and p95 response times

**After test**:

1. **Sampler** → CPU **Snapshot**: identify REST controller hot spots
2. **Monitor tab** → Click **Heap Dump** button
3. In heap dump → **Classes** tab → sort by **Instances**
4. **Open** `reports/scenario3.html` for endpoint-level latency breakdown

**Classes to examine in heap dump**:

- `com.zaxxer.hikari.*` (connection pool objects)
- `org.springframework.web.context.*` (request contexts)
- `java.util.concurrent.*` (thread pool internals)

---

## Data Collection Summary

### For Each Scenario:

| Metric             | Where                               | What to Record                        |
| ------------------ | ----------------------------------- | ------------------------------------- |
| **CPU %**          | VisualVM Monitor tab                | Average CPU during peak load          |
| **Heap MB**        | VisualVM Monitor tab                | Used heap at peak load                |
| **Hot Methods**    | VisualVM Sampler → Snapshot         | Top 5 methods with Self Time %        |
| **Thread Count**   | VisualVM Threads tab                | Total threads, RUNNABLE count         |
| **RPS**            | Locust Charts / HTML report         | Requests per second at each stage     |
| **Response Time**  | Locust Statistics / HTML report     | Median, p95, p99 per endpoint         |
| **Failure Rate**   | Locust Statistics / HTML report     | % failures and failure types          |
| **Breaking Point** | Locust failures + VisualVM together | # users when failures spike / CPU>90% |

### Energy Estimation (Q3.3):

VisualVM does **not** measure energy directly. The assignment says "Estimez ou profilez" — estimation from CPU% is the standard approach.

**Formula**: `Energy (Wh) = (CPU% / 100) × TDP(W) × Duration(hours)`

**For Ryzen 9 4900HS (TDP = 35W)**:

```
Scenario 1 at 100 users for 60s:
  CPU = 65%
  E = 0.65 × 35W × (60/3600)h = 0.379 Wh

Compare to idle (10% CPU):
  E_idle = 0.10 × 35W × (60/3600)h = 0.058 Wh

Energy overhead = 0.379 - 0.058 = 0.321 Wh per minute
```

Record energy at each load stage and compare to idle baseline.

---

## Required Screenshots

### Scenario 1 (WebSocket Load):

- [ ] VisualVM Monitor tab: Heap + CPU graphs over full test duration
- [ ] VisualVM Sampler snapshot: Hot Spots table at 50 users
- [ ] VisualVM Sampler snapshot: Hot Spots table at 100 users
- [ ] VisualVM Threads tab: Thread states at peak load
- [ ] Locust Charts tab: RPS + response times + active users
- [ ] Locust Statistics tab: per-endpoint p95/p99 latencies
- [ ] `reports/scenario1.html` — Locust HTML report

### Scenario 2 (Telemetry Ingestion):

- [ ] VisualVM Sampler CPU snapshot: Hot Spots sorted by Self Time
- [ ] VisualVM Monitor tab: CPU graph during test
- [ ] Locust Charts tab: RPS over time
- [ ] `reports/scenario2.html` — Locust HTML report

### Scenario 3 (Admin Burst):

- [ ] VisualVM Heap dump: Classes sorted by Instances
- [ ] VisualVM Threads tab: Blocked threads during admin burst
- [ ] VisualVM Sampler CPU snapshot: REST method hot spots
- [ ] VisualVM Monitor tab: Heap graph
- [ ] Locust Statistics tab: per-endpoint breakdown
- [ ] `reports/scenario3.html` — Locust HTML report

---

## Critical Analysis Guide

### Breaking Point Identification

**Document for each scenario**:

1. **Max concurrent users** before failure
2. **Error rate** at breaking point
3. **CPU %** at breaking point
4. **Heap MB** at breaking point
5. **Symptoms**: Response time, disconnections, exceptions

### Bottleneck Patterns

**CPU Bottleneck**:

- One method > 20% of CPU in Sampler hot spots
- Examples: `NioEventLoop`, JSON parsing
- Solution: Optimize algorithm, increase threads

**Memory Bottleneck**:

- Heap reaches -Xmx and stays there; heavy GC
- Solution: Increase -Xmx, reduce object retention

**Database Bottleneck**:

- Hot spot: `org.postgresql.jdbc.*` methods
- Threads: Many WAITING on `HikariPool.getConnection()`
- Solution: Increase connection pool size

**Thread Pool Bottleneck**:

- Threads tab: >80% threads BLOCKED
- Solution: Increase thread pool size, use async processing

### Memory Leak Detection

1. Run scenario 1 to peak load
2. Take heap dump → note instance counts for session classes
3. Stop load, wait 5 minutes
4. Force GC (Monitor tab → Perform GC button)
5. Take second heap dump → compare instance counts

**Leak indicators**: `SessionMetaData`, `WebSocketSession` instances don't drop after disconnect.

---

## Troubleshooting

### VisualVM Can't Connect to `localhost:9011`

1. Verify tb-core1 is running: `docker ps | grep tb-core1`
2. Check port is mapped: `docker port docker-tb-core1-1 9011` (should show `0.0.0.0:9011`)
3. Check JMX is listening inside container:
   ```bash
   docker exec docker-tb-core1-1 sh -c "netstat -tlnp | grep 9011"
   ```
4. Check Windows Firewall is not blocking port 9011
5. Restart containers: `bash docker-stop-services.sh && bash docker-start-services.sh`

### Installation Errors

**`$'\r': command not found`**: CRLF line endings in shell/conf files. Fix per Step 1.1.

**`Invalid -Xlog option`**: Same CRLF issue — `\r` character corrupts JVM flags.

### Python / Locust Errors

- **`No devices found`**: Run `python setup_devices.py 50` first
- **`Login failed`**: Check ThingsBoard is running at http://localhost
- **`Connection refused` on WebSocket**: Verify HAProxy is running, port 80 accessible
- **`locust: command not found`**: Activate venv first: `venv\Scripts\activate`
- **Port 8089 in use**: Locust web UI default port conflict — use `--web-port 8090`

### Containers Won't Start

- **`port already in use`**: Stop other services using ports 80, 443, 1883, 9011
- **`Cannot connect to Docker daemon`**: Start Docker Desktop

---

## Quick Reference

### Essential Commands

```bash
# Start ThingsBoard
cd docker
bash docker-start-services.sh

# Stop ThingsBoard
bash docker-stop-services.sh

# View logs
docker logs docker-tb-core1-1 -f
docker logs haproxy-certbot -f

# Check status
docker ps

# Create devices
cd profiling
python setup_devices.py 50

# Run scenarios (with web UI — open http://localhost:8089)
locust -f locustfile.py --class-picker

# Run scenarios (headless with reports)
mkdir -p reports
locust -f locustfile.py WebSocketUser  --headless -u 150 -r 10 -t 6m  --html reports/scenario1.html --csv reports/scenario1
locust -f locustfile.py TelemetryUser  --headless -u 30  -r 10 -t 2m  --html reports/scenario2.html --csv reports/scenario2
locust -f locustfile.py AdminUser      --headless -u 60  -r 15 -t 2m  --html reports/scenario3.html --csv reports/scenario3
```

### Important URLs

- ThingsBoard UI: http://localhost
- HAProxy Stats: http://localhost:9999/stats (admin / admin@123)
- JMX Port (Core 1): localhost:9011

### Login Credentials

- Tenant: tenant@thingsboard.org / tenant
- System Admin: sysadmin@thingsboard.org / sysadmin

---

## Final Pre-Flight Checklist

- [ ] Docker Desktop running
- [ ] ThingsBoard containers up (`docker ps` shows 15+ containers)
- [ ] Can access http://localhost and login
- [ ] VisualVM installed and launched
- [ ] JMX connection successful (`localhost:9011`) — Monitor tab shows live graphs
- [ ] Python 3.8+ with Locust installed (`locust --version`)
- [ ] 50 test devices created
- [ ] Locust web UI accessible at http://localhost:8089 when launched
- [ ] Understand which screenshots to take at each scenario stage
