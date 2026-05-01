# Phase 5 — Locust Benchmark + ADR Report

**Date:** 2026-05-01  
**Author:** Po-Fang Yang (Megan)  
**Goal:** Benchmark 3 deployment strategies under concurrent load, produce Architecture Decision Record

---

## ✅ Checklist

| Step | Status |
|------|--------|
| Locust 2.43.4 installed (venv) | ✅ |
| locustfile.py created | ✅ |
| Scenario A: Single Pod (1 replica) | ✅ |
| Scenario B: HPA Dynamic (min=2, max=6) | ✅ |
| Scenario C: Pre-scaled (4 replicas) | ✅ |
| CSV results exported | ✅ |
| ADR written | ✅ |
| Settings restored (min=2, max=6) | ✅ |

---

## Test Configuration

| Parameter | Value |
|-----------|-------|
| Tool | Locust 2.43.4 |
| Concurrent users | 10 |
| Ramp rate | 2 users/sec |
| Duration | 60 seconds |
| Prompt | ~50 tokens (HPA explanation) |
| Max tokens | 50 |
| Model | Phi-3 Mini (Ollama) |
| Hardware | GTX 1650 Max-Q 4GB VRAM |
| Cluster | k3d (1 server + 2 agents) |

---

## Benchmark Results

### Scenario A — Single Pod (1 replica, no HPA)

```
Total Requests : 22
Failure Rate   : 45.5% (10x HTTP 502)
Avg Latency    : 18,506ms
Min Latency    : 8,469ms
P50 Latency    : 15,000ms
P95 Latency    : 35,000ms
P99 Latency    : 38,000ms
Throughput     : 0.37 req/s
```

### Scenario B — HPA Dynamic (min=2, max=6, CPU target=70%)

```
Total Requests : 20
Failure Rate   : 0%
Avg Latency    : 20,979ms
Min Latency    : 3,798ms
P50 Latency    : 26,000ms
P95 Latency    : 28,000ms
P99 Latency    : 28,000ms
Throughput     : 0.34 req/s
```

### Scenario C — Pre-scaled Static Fleet (4 replicas, no HPA)

```
Total Requests : 23
Failure Rate   : 0%
Avg Latency    : 17,938ms
Min Latency    : 2,665ms
P50 Latency    : 22,000ms
P95 Latency    : 24,000ms
P99 Latency    : 24,000ms
Throughput     : 0.40 req/s
```

---

## Comparison Table

| Metric | A: Single Pod | B: HPA Dynamic | C: Pre-scaled 4 |
|--------|:---:|:---:|:---:|
| Requests | 22 | 20 | 23 |
| Failure Rate | **45.5%** ❌ | **0%** ✅ | **0%** ✅ |
| P50 Latency | 15s | 26s | 22s |
| P95 Latency | 35s ❌ | 28s ✅ | **24s** ✅✅ |
| Throughput | 0.37 req/s | 0.34 req/s | **0.40 req/s** ✅✅ |
| Idle Pods | 1 | 2 (min) | 4 |
| Scale-up Lag | N/A | 30-60s | None |
| Cost Efficiency | High ✅✅ | Medium ✅ | Low ❌ |

---

## Key Findings

1. **Single Pod is not production-viable** — 45% failure rate under just 10 concurrent users due to Ollama backend queue overflow (HTTP 502)

2. **HPA eliminates failures** — Scaling to 2 pods distributes load sufficiently for 10 concurrent users at 0% failure rate

3. **Pre-scaling gives best latency** — 4 pods reduces P95 by 14% vs HPA (24s vs 28s) due to no scale-up lag

4. **Throughput difference is minimal** — All scenarios achieve ~0.37-0.40 req/s, bottlenecked by single GPU inference backend

---

## ADR Decision

**Recommended: Scenario B (HPA Dynamic)** for production workloads.

Rationale: 0% failure rate with automatic cost optimization. Pre-scaling (C) only preferred for latency-critical, predictable-load use cases.

See full ADR: `docs/adr-inference-strategy.md`

---

## Locust Command Reference

```bash
# Scenario A
kubectl scale deployment llm-inference --replicas=1
kubectl patch hpa llm-inference-hpa -p '{"spec":{"minReplicas":1,"maxReplicas":1}}'
~/locust-env/bin/locust -f benchmark/locustfile.py --headless \
  -u 10 -r 2 -t 60s --host http://localhost:8000 \
  --csv benchmark/results/scenario-a --csv-full-history

# Scenario B
kubectl patch hpa llm-inference-hpa -p '{"spec":{"minReplicas":2,"maxReplicas":6}}'
kubectl scale deployment llm-inference --replicas=2
~/locust-env/bin/locust -f benchmark/locustfile.py --headless \
  -u 10 -r 2 -t 60s --host http://localhost:8000 \
  --csv benchmark/results/scenario-b --csv-full-history

# Scenario C
kubectl patch hpa llm-inference-hpa -p '{"spec":{"minReplicas":4,"maxReplicas":4}}'
kubectl scale deployment llm-inference --replicas=4
~/locust-env/bin/locust -f benchmark/locustfile.py --headless \
  -u 10 -r 2 -t 60s --host http://localhost:8000 \
  --csv benchmark/results/scenario-c --csv-full-history

# Restore
kubectl patch hpa llm-inference-hpa -p '{"spec":{"minReplicas":2,"maxReplicas":6}}'
kubectl scale deployment llm-inference --replicas=2
```


