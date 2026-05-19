# 关于语言模型的选择
## （一）在线LLM
可选范围较大：Qwen，Deepseek，GLM，Kimi，MiniMax等。

比如在提供商（阿里巴巴）的情况下：
优先考虑Qwen/Deepseek的flash小模型进行意图识别，再用你喜欢的大模型进行知识检索。

- deepseek：https://api.deepseek.com/v1
- 阿里百炼：https://dashscope.aliyuncs.com/compatible-mode/v1

如果使用国外提供商和LLM，比如OpenAI，Anthropic，Google，xAI(Grok)等，可能需要修改代码以便关闭推理模式。

---

## （二）本地LLM
完全本地运行, 需要开源模型。
在显存不大的情况下，比较依赖模型选择和配置。

### （2.1）原则
根据本地计算机性能，选择适合你的模型和软件支持。
1. 显存优先，首要考虑不要使用共享显存。需要观察计算额外显存消耗（软件，KV，视觉部分）。
2. 大模型的极端量化版本，优于同等文件尺寸的小模型。
3. 选择能关闭推理模式(Thinking Mode)的模型。比如gpt-oss无法完全关闭推理，速度和token消耗会有些影响。
4. 显存足够的情况下，可考虑 MTP[^1] ，DFlash[^2] 等技术，提高输出效率。
5. 不要选Ollama做后端，像饿了吗这种为了方便的软件效率不够。可选支持GGUF，MTP，DFlash等技术软件做LLM后端。

### （2.2）模型推荐
根据自己的测试，基于我的配置（12900f+64GB+4060Ti16GB），推荐以下模型：
1. Gemma4: 比如 `gemma-4-26B-A4B-it-UD-IQ2_M.gguf`+`mmproj`。综合表现好。
2. Qwen3.6: 比如 `Qwen3.6-35B-A3B-UD-IQ1_M_MTP.gguf`+`mmproj`。不太信任视觉部分，偏大，量化得太猛。
3. GPT-OSS: 比如 `gpt-oss-20b-Q4_0.gguf` ⚠️ 无视觉部分，速度快，回答比较有特点。

### （2.3）后端软件
因为我全程Windows下运行，所以使用`Llama.cpp`作为后端，目前已官方支持MTP。
但默认启动参数依然容易爆显存，所以根据模型，我的启动参数如下，可供参考。

---

**Gemma4**：
```powershell
.\llama-server.exe `
    -m gemma-4-26B-A4B-it-UD-IQ2_M.gguf `
    --mmproj gemma-4-26B-A4B-mmproj-BF16.gguf `
    --no-mmproj-offload `
    --gpu-layers auto `
    --ctx-size 8192 `
    -fa on `
    --reasoning off `
    --host 127.0.0.1 --port 8999 `
    --log-timestamps `
    --offline `
    --threads 4 `
    --threads-batch 8 `
    --parallel 1 `
    -ctk q4_0 -ctv q4_0 `
    --no-cont-batching `
    --poll 0 `
    --no-ui
```

---

**Qwen3.6** (MTP)：
```powershell
.\llama-server.exe `
    -m Qwen3.6-35B-A3B-UD-IQ1_M_MTP.gguf `
    --gpu-layers auto `
    --ctx-size 8192 `
    -fa on `
    --reasoning off `
    --spec-type draft-mtp --spec-draft-n-max 2 `
    --host 127.0.0.1 --port 8999 `
    --offline `
    --threads 4 `
    --threads-batch 8 `
    --parallel 1 `
    -ctk q4_0 -ctv q4_0 `
    --no-cont-batching `
    --poll 0 `
    --no-ui
```

---

**GPT-OSS** (理论上none应该会fallback成low)：
```powershell
.\llama-server.exe `
    -m gpt-oss-20b-Q4_0.gguf `
    --gpu-layers auto `
    --ctx-size 8192 `
    -fa on `
    --chat-template-kwargs '{"reasoning_effort":"none" }' `
    --host 127.0.0.1 --port 8999 `
    --log-timestamps `
    --offline `
    --threads 4 `
    --threads-batch 8 `
    --parallel 1 `
    -ctk q4_0 -ctv q4_0 `
    --no-cont-batching `
    --poll 0 `
    --no-ui
```

---

[^1]: Multi-token Prediction

[^2]: Block Diffusion for Flash Speculative Decoding
