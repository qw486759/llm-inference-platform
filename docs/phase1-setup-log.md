# Phase 1 — WSL2 Environment + Ollama Setup

This phase covers the initial environment setup: installing WSL2 Ubuntu, verifying GPU access, and confirming that Ollama can run Phi-3 Mini with GPU acceleration before any containerization or orchestration work begins.

---

## Checklist

| Step | Status |
|------|--------|
| WSL2 Ubuntu 24.04 installed | ✅ |
| NVIDIA Driver 596.36 (CUDA 13.2) | ✅ |
| Docker Desktop WSL2 integration | ✅ |
| Ollama 0.22.1 installed | ✅ |
| Phi-3 Mini (2.2GB) pulled | ✅ |
| GPU inference confirmed | ✅ |
| Cold start latency | 81s (model load into VRAM) |
| Warm inference latency | **0.05s eval / 0.3s end-to-end** |

---

## GPU Verification

```
$ nvidia-smi
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 595.71.01              Driver Version: 596.36         CUDA Version: 13.2     |
+-----------------------------------------+------------------------+----------------------+
|   0  NVIDIA GeForce GTX 1650 ...    On  |   00000000:02:00.0 Off |                  N/A |
| N/A   55C    P8              3W /   30W |    3338MiB /   4096MiB |      0%      Default |
+-----------------------------------------------------------------------------------------+
|    0   N/A  N/A             836      C   /ollama                               N/A      |
+-----------------------------------------------------------------------------------------+
```

Ollama occupies 3338 MiB of the 4096 MiB VRAM, confirming GPU inference is active.

---

## Ollama Installation

```bash
sudo apt-get install -y zstd
curl -fsSL https://ollama.com/install.sh | sh
ollama --version
# ollama version is 0.22.1
```

Ollama registers as a systemd service on installation and auto-detects the NVIDIA GPU.

---

## Model Pull

```bash
ollama pull phi3:mini
# pulling 633fc5be925f: 100% 2.2 GB
# success

ollama list
# NAME         ID              SIZE
# phi3:mini    4f2222927938    2.2 GB
```

---

## Inference Test

**Cold start** (model loading from disk into VRAM):

```bash
$ time curl -s http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"phi3:mini","messages":[{"role":"user","content":"Say hello in one word."}],"stream":false}' \
  | python3 -m json.tool

{
    "model": "phi3:mini",
    "message": {"role": "assistant", "content": "Hello."},
    "load_duration": 71450962528,
    "eval_duration": 97897538
}
real    1m21.280s
```

**Warm inference** (model already resident in VRAM):

```bash
$ time curl -s http://localhost:11434/api/chat ... \
  | python3 -c "..."

Hello
eval: 0.05s
real    0m0.297s
```

The 81-second cold start reflects the time to load the 2.2 GB model into a 4 GB GPU. Subsequent requests complete in under 300ms end-to-end.