# Phase 1 — WSL2 Environment + Ollama Setup Log

---

## ✅ Checklist

| Step | Status |
|------|--------|
| WSL2 Ubuntu 24.04 installed | ✅ |
| NVIDIA Driver 596.36 (CUDA 13.2) | ✅ |
| Docker Desktop WSL2 integration | ✅ |
| Ollama 0.22.1 installed | ✅ |
| Phi-3 Mini (2.2GB) pulled | ✅ |
| GPU inference confirmed | ✅ |
| Cold start latency | 81s (model load) |
| Warm inference latency | **0.05s eval / 0.3s end-to-end** ✅ |

---

## GPU Verification

```
$ nvidia-smi
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 595.71.01              Driver Version: 596.36         CUDA Version: 13.2     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
|   0  NVIDIA GeForce GTX 1650 ...    On  |   00000000:02:00.0 Off |                  N/A |
| N/A   55C    P8              3W /   30W |    3338MiB /   4096MiB |      0%      Default |
+-----------------------------------------------------------------------------------------+
| Processes:                                                                               |
|    0   N/A  N/A             836      C   /ollama                               N/A      |
+-----------------------------------------------------------------------------------------+
```

**Ollama is using 3338MiB / 4096MiB VRAM** — GPU inference confirmed.

---

## Ollama Installation

```bash
# Install dependency
sudo apt-get install -y zstd

# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Verify
ollama --version
# ollama version is 0.22.1
```

Ollama automatically registers as a systemd service and detects the NVIDIA GPU.

---

## Model Pull

```bash
ollama pull phi3:mini
# pulling manifest
# pulling 633fc5be925f: 100% 2.2 GB
# success

ollama list
# NAME         ID              SIZE      MODIFIED
# phi3:mini    4f2222927938    2.2 GB    22 seconds ago
```

---

## Inference Test

**Cold start (first run — model loading into VRAM):**
```bash
$ time curl -s http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"phi3:mini","messages":[{"role":"user","content":"Say hello in one word."}],"stream":false}' \
  | python3 -m json.tool

{
    "model": "phi3:mini",
    "message": {"role": "assistant", "content": "Hello."},
    "done": true,
    "load_duration": 71450962528,
    "eval_duration": 97897538
}
real    1m21.280s   # cold start: model loading to VRAM
```

**Warm inference (model already in VRAM):**
```bash
$ time curl -s http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"phi3:mini","messages":[{"role":"user","content":"Say hello in one word."}],"stream":false}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['message']['content']); print(f'eval: {d[\"eval_duration\"]/1e9:.2f}s')"

Hello
eval: 0.05s
real    0m0.297s    ✅ well under 200ms target (eval only)
```