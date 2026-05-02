# Phase 5 — Locust Benchmark

This phase uses Locust to apply concurrent load across three deployment configurations and records the resulting latency, throughput, and failure metrics. The data feeds directly into the Architecture Decision Record (`docs/adr-inference-strategy.md`).

---

## Checklist

| Step | Status |
|------|--------|
| Locust 2.43.4 installed | ✅ |
| locustfile.py written | ✅ |
| Scenario A: Single pod (1 replica) | ✅ |
| Scenario B: HPA dynamic (min=2, max=6) | ✅ |
| Scenario C: Pre-scaled (4 replicas) | ✅ |
| CSV results exported | ✅ |
| ADR written | ✅ |
| Settings restored to default (min=2, max=6) | ✅ |

---

## Test Configuration

| Parameter | Value |
|-----------|-------|
| Tool | Locust 2.43.4 |
| Concurrent users | 10 |
| Ramp rate | 2 users/sec |
| Duration | 60 seconds |
| Prompt | Fixed ~50-token prompt |
| Max tokens | 50 |
| Model | Phi-3 Mini via Ollama |
| Hardware | GTX 1650 Max-Q, 4GB VRAM |
| Cluster | k3d, 1 server + 2 agents |

---

## Results

### Scenario A — Single pod

```
Total Requests : 22
Failure Rate   : 45.5% (10x HTTP 502)
P50 Latency    : 15,000ms
P95 Latency    : 35,000ms
Throughput     : 0.37 req/s
```

### Scenario B — HPA dynamic (min=2, max=6)

```
Total Requests : 20
Failure Rate   : 0%
P50 Latency    : 26,000ms
P95 Latency    : 28,000ms
Throughput     : 0.34 req/s
```

### Scenario C — Pre-scaled (4 replicas)

```
Total Requests : 23
Failure Rate   : 0%
P50 Latency    : 22,000ms
P95 Latency    : 24,000ms
Throughput     : 0.40 req/s
```

---

## Summary

| Metric | A: Single Pod | B: HPA Dynamic | C: Pre-scaled 4 |
|--------|:---:|:---:|:---:|
| Failure Rate | **45.5%** ❌ | **0%** ✅ | **0%** ✅ |
| P50 Latency | 15s | 26s | 22s |
| P95 Latency | 35s | 28s | **24s** |
| Throughput | 0.37 req/s | 0.34 req/s | **0.40 req/s** |
| Idle Pods | 1 | 2 (min) | 4 |

**Key observations:**
- Single-pod deployment fails under 10 concurrent users due to Ollama's serial queue overflowing (HTTP 502)
- Both multi-pod configurations eliminate failures entirely
- Pre-scaling achieves lower P95 latency because pods are already warm when the load arrives
- Throughput differences are small across all three scenarios — the bottleneck is the single Ollama backend, not the number of FastAPI pods

See [`docs/adr-inference-strategy.md`](adr-inference-strategy.md) for the full decision record.

---

## Benchmark Commands

```bash
# Scenario A — single pod
kubectl patch hpa llm-inference-hpa -p '{"spec":{"minReplicas":1,"maxReplicas":1}}'
kubectl scale deployment llm-inference --replicas=1
~/locust-env/bin/locust -f benchmark/locustfile.py --headless \
  -u 10 -r 2 -t 60s --host http://localhost:8000 \
  --csv benchmark/results/scenario-a --csv-full-history

# Scenario B — HPA dynamic
kubectl patch hpa llm-inference-hpa -p '{"spec":{"minReplicas":2,"maxReplicas":6}}'
kubectl scale deployment llm-inference --replicas=2
~/locust-env/bin/locust -f benchmark/locustfile.py --headless \
  -u 10 -r 2 -t 60s --host http://localhost:8000 \
  --csv benchmark/results/scenario-b --csv-full-history

# Scenario C — pre-scaled
kubectl patch hpa llm-inference-hpa -p '{"spec":{"minReplicas":4,"maxReplicas":4}}'
kubectl scale deployment llm-inference --replicas=4
~/locust-env/bin/locust -f benchmark/locustfile.py --headless \
  -u 10 -r 2 -t 60s --host http://localhost:8000 \
  --csv benchmark/results/scenario-c --csv-full-history

# Restore default
kubectl patch hpa llm-inference-hpa -p '{"spec":{"minReplicas":2,"maxReplicas":6}}'
kubectl scale deployment llm-inference --replicas=2
```