# ADR-001: LLM Inference Deployment Strategy

**Date:** 2026-05-01  
**Author:** Po-Fang Yang  
**Status:** Accepted  
**Context:** LLM Inference Platform on Kubernetes — Northeastern University / Advanced LLM Techniques

---

## Context

We are deploying a production-style LLM inference service (Phi-3 Mini via Ollama, wrapped in FastAPI) on a Kubernetes cluster. The service must handle variable concurrent load while balancing latency, reliability, and resource cost.

The core question: **which pod scaling strategy best serves LLM inference workloads?**

LLM inference has unique characteristics that make this decision non-trivial:
- High per-request latency (seconds, not milliseconds)
- GPU/CPU resource contention under concurrent load
- Cold-start penalty when new pods initialize
- Unpredictable token generation length affects response time

---

## Options Considered

### Option A: Single Pod (No Autoscaling)
Deploy exactly 1 replica with no HPA. Simplest configuration, lowest idle resource cost.

### Option B: HPA Dynamic Scaling (min=2, max=6, target CPU=70%)
Deploy with Horizontal Pod Autoscaler that reactively scales based on CPU utilization. Balances cost and capacity.

### Option C: Pre-scaled Static Fleet (4 replicas, no HPA)
Deploy a fixed pool of 4 replicas. Maximum throughput at the cost of always-on resource usage.

---

## Benchmark Results

All scenarios tested under 10 concurrent users, 60-second duration, fixed 50-token prompt on GTX 1650 Max-Q (4GB VRAM), k3d local cluster.

| Metric | Scenario A (1 Pod) | Scenario B (HPA 2→6) | Scenario C (4 Pods) |
|--------|-------------------|----------------------|---------------------|
| Total Requests | 22 | 20 | 23 |
| Failure Rate | **45.5%** | **0%** | **0%** |
| Avg Latency | 18,506ms | 20,979ms | 17,938ms |
| Min Latency | 8,469ms | 3,798ms | 2,665ms |
| P50 Latency | 15,000ms | 26,000ms | 22,000ms |
| P95 Latency | 35,000ms | 28,000ms | **24,000ms** |
| P99 Latency | 38,000ms | 28,000ms | **24,000ms** |
| Throughput | 0.37 req/s | 0.34 req/s | **0.40 req/s** |
| Error Type | HTTP 502 | None | None |
| Idle Pod Count | 1 | 2 (min) | 4 |

---

## Comparison Table

| Dimension | A: Single Pod | B: HPA Dynamic | C: Pre-scaled 4 |
|-----------|--------------|----------------|-----------------|
| P95 Latency | 35s ❌ | 28s ✅ | 24s ✅✅ |
| Failure Rate | 45% ❌ | 0% ✅ | 0% ✅ |
| Throughput | 0.37 req/s ❌ | 0.34 req/s ✅ | 0.40 req/s ✅✅ |
| Idle Cost | Low ✅✅ | Medium ✅ | High ❌ |
| Scale-up Lag | N/A | 30-60s ⚠️ | None ✅✅ |
| Operational Complexity | Low ✅✅ | Medium ✅ | Low ✅✅ |
| Cold-start Risk | High ❌ | Medium ⚠️ | Low ✅ |
| Production Readiness | ❌ | ✅ | ✅✅ |

---

## Decision

**Recommended: Scenario B (HPA Dynamic Scaling)** for production workloads with variable traffic.

**Rationale:**

1. **Reliability over raw performance.** Scenario A's 45% failure rate is unacceptable in any production environment. Both B and C achieve 0% failure rate.

2. **Cost efficiency at scale.** Scenario C's 4-pod static fleet consumes 4x the resources at idle. For a real deployment, this means 4x compute cost even during off-peak hours. HPA scales down to 2 pods when load is low.

3. **P95 latency is acceptable.** HPA achieves P95=28s vs C's 24s — a 4-second difference that is within acceptable range for LLM inference workloads where users already expect multi-second responses.

4. **Operational flexibility.** HPA automatically responds to traffic spikes without manual intervention, which aligns with AI factory operational principles.

**Exception:** Scenario C is preferred for **latency-sensitive, predictable-load** use cases (e.g., batch processing pipelines, real-time voice interfaces) where the 4s P95 improvement justifies the cost premium.

---

## Consequences

### Positive
- 0% failure rate under 10 concurrent users with HPA
- Automatic scale-out during traffic spikes (up to 6 pods)
- Automatic scale-in during low traffic reduces idle cost
- No manual intervention required for typical load patterns

### Negative
- HPA scale-up introduces 30-60 second lag before new pods become ready
- During scale-up window, existing pods absorb increased load, temporarily increasing latency
- Minimum 2 pods always running (cannot scale to zero without KEDA)

### Risks & Mitigations
| Risk | Mitigation |
|------|-----------|
| Scale-up lag causes latency spikes | Pre-warm with minReplicas=2; tune HPA scale-up stabilization window |
| GPU memory contention with multiple pods | Each pod shares CPU inference; GPU used by Ollama directly — not per-pod |
| HPA thrashing (rapid scale up/down) | Set `scaleDown.stabilizationWindowSeconds: 300` in HPA spec |

---

## Future Considerations

- **KEDA (Kubernetes Event-driven Autoscaling):** Scale on request queue depth rather than CPU — more accurate for LLM workloads where CPU may not reflect actual inference load
- **vLLM migration:** Replace Ollama with vLLM for continuous batching, which would dramatically improve throughput and reduce per-request latency
- **AWS EKS + GPU nodes:** Move from local k3d to cloud deployment with NVIDIA A10G instances for production-grade GPU inference
- **Request queuing:** Add Redis-based queue in front of the inference service to absorb burst traffic and prevent 502 errors

---

## References

- Benchmark tool: Locust 2.43.4
- Model: Phi-3 Mini (2.2GB, 4-bit quantized)
- Hardware: NVIDIA GTX 1650 Max-Q (4GB VRAM), 16GB RAM
- Cluster: k3d v5.8.3 (k3s v1.31.5), 1 server + 2 agents
- Test parameters: 10 concurrent users, ramp 2/s, 60s duration
