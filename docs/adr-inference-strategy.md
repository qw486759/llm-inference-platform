# ADR-001: LLM Inference Deployment Strategy

This document records the deployment strategy evaluation for a Kubernetes-hosted LLM inference service. The goal was to systematically compare how deployment configuration affects reliability, latency, and resource usage under concurrent load — moving beyond a basic inference API into measurable architecture trade-offs.

---

## Context

The inference service wraps Phi-3 Mini (via Ollama) in a FastAPI layer and runs on a local Kubernetes cluster. The service needs to handle variable concurrent load while balancing latency, reliability, and resource cost.

The central question: **which pod scaling strategy best serves this LLM inference workload?**

LLM inference has characteristics that make this a non-trivial systems problem:
- Per-request latency is measured in seconds, not milliseconds
- GPU and CPU resources contend under concurrent load
- New pods incur a cold-start penalty before becoming ready
- Token generation length is variable, affecting tail latency

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

All scenarios tested under 10 concurrent users, 60-second duration, fixed 50-token prompt.
Hardware: NVIDIA GTX 1650 Max-Q (4GB VRAM), k3d local cluster.

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
| Scale-up Lag | N/A | 30–60s ⚠️ | None ✅✅ |
| Operational Complexity | Low ✅✅ | Medium ✅ | Low ✅✅ |
| Cold-start Risk | High ❌ | Medium ⚠️ | Low ✅ |

---

## Decision

**Recommended: Scenario B (HPA Dynamic Scaling)** for variable-traffic workloads.

**Rationale:**

1. **Reliability over raw performance.** Scenario A's 45% failure rate is unacceptable under any reasonable load. Both B and C achieve 0% failure rate.

2. **Cost efficiency.** Scenario C's 4-pod static fleet consumes 4× the idle resources. HPA scales down to minReplicas=2 during low-traffic periods, reducing waste.

3. **Latency trade-off is acceptable.** HPA achieves P95=28s versus C's 24s — a 4-second difference that is within a reasonable range for workloads where multi-second responses are already expected.

4. **Operational simplicity.** HPA responds automatically to load changes, avoiding the need for manual scaling decisions.

**Exception:** Scenario C is preferred for latency-sensitive, predictable-load use cases (e.g., batch processing pipelines or real-time voice interfaces) where the 4s P95 improvement justifies the higher idle cost.

---

## Consequences

### Positive
- 0% failure rate under 10 concurrent users
- Automatic scale-out during traffic spikes (up to 6 pods)
- Automatic scale-in during low traffic reduces idle cost
- No manual intervention required for typical load patterns

### Negative
- HPA scale-up introduces 30–60 second lag before new pods are ready
- During the scale-up window, existing pods absorb additional load
- Minimum 2 pods always running (cannot scale to zero without KEDA)

### Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Scale-up lag causes latency spikes | Pre-warm with `minReplicas=2`; tune HPA scale-up stabilization window |
| GPU memory contention across pods | Ollama holds the GPU directly; FastAPI pods use CPU only |
| HPA thrashing under oscillating load | Set `scaleDown.stabilizationWindowSeconds: 300` in HPA spec |

---

## Future Directions

- **KEDA:** Scale on request queue depth rather than CPU utilization — more meaningful for LLM workloads where CPU does not directly reflect inference load
- **vLLM:** Replace Ollama with vLLM for continuous batching, which would substantially improve throughput and reduce per-request latency
- **Cloud deployment:** Move from local k3d to a cloud cluster with GPU-enabled nodes for production-scale evaluation
- **Request queuing:** Add a queue layer (e.g., Redis) in front of the inference service to absorb burst traffic without 502 errors

---

## GPU Bottleneck Analysis

Benchmark results reveal an important architectural constraint: **adding FastAPI gateway pods does not proportionally increase inference throughput**, because all requests ultimately converge on a single GPU-backed Ollama runtime.

| Scenario | Gateway Pods | GPU Backend | Failure Rate | P95 Latency | Throughput | Bottleneck |
|----------|-------------|-------------|-------------|-------------|------------|------------|
| A: Single Pod | 1 | 1× GTX 1650 | 45.5% ❌ | 35s | 0.37 req/s | API queue overflow + GPU serialization |
| B: HPA Dynamic | 2→6 | 1× GTX 1650 | 0% ✅ | 28s | 0.34 req/s | HPA warm-up lag + shared GPU backend |
| C: Pre-scaled | 4 | 1× GTX 1650 | 0% ✅ | 24s | 0.40 req/s | Shared GPU backend |

**Key insight:** Throughput variance across scenarios is only 0.06 req/s (0.34→0.40), despite a 4× difference in pod count. This confirms the bottleneck is the **single GPU backend**, not the API gateway layer.

This exposes the distinction between two separate scaling dimensions:
- **Gateway scalability** — handled by Kubernetes HPA, eliminates request queue overflow and 502 errors
- **Accelerator capacity** — fixed by hardware; true horizontal scaling requires either multiple GPU nodes or a batching-capable serving runtime

For production GPU inference scaling, the correct approach is not more gateway pods, but a runtime that can saturate the GPU through concurrent batching — such as vLLM (continuous batching) or NVIDIA Triton Inference Server (dynamic batching with TensorRT-LLM backend).

Measured GPU inference throughput on this hardware: **~20 tokens/sec** on NVIDIA GTX 1650 Max-Q (CUDA 13.2), Phi-3 Mini 4-bit quantized.

---

## Production GPU Deployment Path

The local benchmark uses host-level Ollama GPU acceleration because the test environment runs on WSL2 + k3d, which does not support GPU passthrough to Kubernetes pods. The production migration path is documented in `k8s/gpu-deployment.example.yaml`.

For a production GPU-enabled Kubernetes cluster, the key changes are:

| Component | Local (this project) | Production |
|-----------|---------------------|------------|
| GPU access | Host Ollama via `host.docker.internal` | NVIDIA Device Plugin + `nvidia.com/gpu: 1` per pod |
| Serving runtime | Ollama (dev-friendly, serial queue) | vLLM (continuous batching) or Triton (multi-model) |
| Scaling signal | CPU utilization (HPA) | Queue depth or tokens/sec (KEDA) |
| GPU observability | nvidia-smi on host | NVIDIA DCGM Exporter → Prometheus |

---

## References

- Benchmark tool: Locust 2.43.4
- Model: Phi-3 Mini (2.2GB, 4-bit quantized)
- Hardware: NVIDIA GTX 1650 Max-Q (4GB VRAM), 16GB RAM
- Cluster: k3d v5.8.3 (k3s v1.31.5), 1 server + 2 agents
- Test parameters: 10 concurrent users, ramp 2 users/s, 60s duration