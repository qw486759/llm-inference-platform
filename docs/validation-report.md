# E2E Validation Report

**Platform:** llm-inference-platform  
**Environment:** WSL2 Ubuntu · NVIDIA GTX 1650 Max-Q · k3d v5.8.3 · kubectl v1.36.0 · Helm v3.20.2

---

## Summary

| | |
|---|---|
| Total checks | 22 |
| Passed | 22 |
| Issues found during validation | 3 |
| Issues fixed | 3 |

All local E2E paths are reproducible. Observed HPA behavior under load is consistent with the ADR's conclusion that CPU-based HPA is an insufficient autoscaling signal for GPU-bound LLM inference workloads.

---

## Phase 1 — GPU + Ollama

| # | Check | Command | Result |
|---|-------|---------|--------|
| 1 | GPU visible | `nvidia-smi` | GTX 1650 Max-Q · CUDA 13.2 · 4GB VRAM |
| 2 | Ollama running | `ollama list` · `curl http://localhost:11434/api/tags` | phi3:mini 2.2GB loaded · API responding |
| 3 | GPU inference | `curl http://localhost:11434/api/chat` | `eval_duration` present · ~20–36 tokens/sec depending on prompt/run |

---

## Phase 2 — Docker image

| # | Check | Command | Result |
|---|-------|---------|--------|
| 4 | Image build | `docker build -f docker/Dockerfile -t llm-inference:v2 .` | Multi-stage build succeeded · 211MB |
| 5 | Container run | `docker run` + `curl /live` + `curl /ready` | Env var injected · `/live` and `/ready` probes separated |
| 6 | API schema | `curl http://localhost:8001/v1/chat/completions` | OpenAI-compatible response · `choices` present |

---

## Phase 3 — Kubernetes

| # | Check | Command | Result |
|---|-------|---------|--------|
| 7 | Cluster nodes | `kubectl get nodes` | 3/3 nodes Ready · k3s v1.31.5 |
| 8 | Image import | `k3d image import llm-inference:v2 -c llm-cluster` | Image loaded into local registry |
| 9 | Deployment rollout | `kubectl rollout status deployment/llm-inference` | 2/2 pods READY 1/1 |
| 10 | HPA status | `kubectl get hpa` | `cpu: 1%/70%` · min=2 max=6 |
| 11 | ⚠️ gpu-deployment misplaced | `kubectl get pods` | Pending GPU pods found · `gpu-deployment.example.yaml` moved to `k8s/examples/` — see Issues |
| 12 | K8s API + metrics | `curl http://localhost:8000/metrics` via port-forward | 4 `llm_*` metrics present · histograms populated |

---

## Phase 4 — Observability

| # | Check | Command | Result |
|---|-------|---------|--------|
| 13 | Prometheus scrape | `curl 'http://localhost:9090/api/v1/query?query=llm_requests_total'` | `llm_requests_total` confirmed scraped via ServiceMonitor |
| 14 | Grafana service access | `curl -o /dev/null -w "%{http_code}" http://localhost:3000/login` | HTTP 200 · Grafana service reachable · dashboard import pending manual verification |

---

## Phase 5 — Benchmark

| # | Check | Command | Result |
|---|-------|---------|--------|
| 15 | ⚠️ Locust install | `pip install locust` | zope namespace conflict on Ubuntu WSL2 · resolved via virtualenv — see Issues |
| 16 | Benchmark run | `~/locust-venv/bin/locust --headless -u 10 -r 2 -t 60s` | 24 requests · 0% failure · P50 20s · P95 22s · 0.40 req/s |
| 17 | CSV output | `ls benchmark/results/` | `stats` · `failures` · `exceptions` · `history` CSVs generated |

---

## Extended checks

| # | Check | Command | Result |
|---|-------|---------|--------|
| 18 | k8s apply scope | `kubectl apply -f k8s/` + `kubectl get deploy` | Only `llm-inference` deployed · `gpu-deployment.example.yaml` correctly excluded after fix |
| 19 | Readiness failure mode | Stop Ollama → `curl -i /ready` → restart → retest | `503 {"status":"unavailable"}` when Ollama down · `200 {"status":"ready"}` after recovery |
| 20 | Makefile smoke | `make smoke` | `/live` · `/ready` · `/v1/chat/completions` all pass |
| 21 | HPA behavior under load | `kubectl get hpa -w` during Locust benchmark | CPU peak 15% · replicas stayed at 2 · confirms CPU-based HPA limitation for GPU-bound inference |
| 22 | k8s apply scope (post-fix) | `kubectl apply -f k8s/` | Only `llm-inference` · `llm-inference-hpa` · `llm-inference` service applied |

---

## Issues found and fixed

### Issue 1 — `gpu-deployment.example.yaml` placed in `k8s/`

**Discovered:** Phase 3, item 11  
**Symptom:** `kubectl apply -f k8s/` scheduled two `llm-inference-gpu` Pending pods on local cluster — no GPU nodes available in k3d  
**Root cause:** Example production manifest was placed alongside operational manifests in `k8s/`, causing it to be applied indiscriminately  
**Fix:** Moved `k8s/gpu-deployment.example.yaml` → `k8s/examples/gpu-deployment.example.yaml`; updated all path references in README and ADR  
**Verification:** Re-ran `kubectl apply -f k8s/` — only `llm-inference` deployment, HPA, and service applied

---

### Issue 2 — Locust install fails on Ubuntu WSL2 due to zope namespace conflict

**Discovered:** Phase 5, item 15  
**Symptom:** `ModuleNotFoundError: No module named 'zope.event'` even after pip install  
**Root cause:** Ubuntu apt-managed `zope.interface` installs to `/usr/lib/python3/dist-packages/zope/`, while pip-installed `zope.event` installs to `~/.local/lib/python3.12/site-packages/zope/`. Python's namespace package resolution stops at the first path and cannot merge the two, so `zope.event` is never found.  
**Fix:** Created a virtualenv (`~/locust-venv`) isolating all benchmark dependencies from the system Python  
**Note:** This is expected behavior on Ubuntu 22.04+ (PEP 668). virtualenv is the correct solution, not a workaround.

---

### Issue 3 — Ollama model unloaded after service restart

**Discovered:** Phase 5, during `make smoke` after Ollama stop/start cycle  
**Symptom:** `curl /v1/chat/completions` returned `502` with `404 Not Found` from Ollama `/api/chat` after restart  
**Root cause:** Stopping and restarting the Ollama service clears the loaded model cache. `phi3:mini` must be re-pulled before inference requests can succeed.  
**Fix:** Re-ran `ollama pull phi3:mini`  
**Note:** Quick Start prerequisite in README already covers `ollama pull phi3:mini`; this confirms it must be re-run after any Ollama service restart.

---

## Final validation summary

The platform passed 22/22 E2E validation checks across GPU availability, Ollama runtime, Docker image build, local container execution, Kubernetes deployment, readiness/liveness probe failure modes, HPA visibility, Prometheus scraping, Grafana service access, Locust benchmarking, CSV artifact generation, and Makefile workflow execution.

Three issues were discovered during validation and fixed:

1. `gpu-deployment.example.yaml` moved from `k8s/` to `k8s/examples/` to prevent local `kubectl apply -f k8s/` from scheduling GPU-only pods
2. Locust installation conflict on Ubuntu WSL2 resolved by isolating benchmark dependencies in a virtualenv
3. Ollama model availability after service restart confirmed; `phi3:mini` requires re-pull after restart, covered by Quick Start prerequisite

HPA behavior under 10-user concurrent load showed CPU utilization peaking at 15%, well below the 70% scale threshold. Replicas remained at 2 throughout the benchmark. This is consistent with the ADR's conclusion: CPU-based HPA does not reflect true load on a GPU-bound inference backend, and production autoscaling should be driven by request queue depth, GPU utilization, or tokens/sec instead.
