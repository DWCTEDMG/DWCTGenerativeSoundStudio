# Studio Hugging Face deployments

Created under `gulle1155` on 2026-10-09. Credentials are Space secrets, never repository files.

| Deployment | Address | Compute |
|---|---|---|
| HunyuanVideo 1.5 endpoint | https://6ac883da53d27c9b5cb0cbf7.endpoints.huggingface.cloud | AWS us-east-2 RTX PRO 6000 96 GB; $2.75/running hour at creation; zero replicas after 15 idle minutes |
| HunyuanVideo 1.5 preview | https://huggingface.co/spaces/gulle1155/hunyuan-video-1-5-zerogpu | Direct ZeroGPU inference, xlarge allocation |
| Nemotron NVFP4 endpoint | https://6ac87f4453d27c9b5cb0cba8.endpoints.huggingface.cloud/v1 | Dedicated endpoint; separate billing |
| Nemotron preview | https://huggingface.co/spaces/gulle1155/nemotron-3-nano-omni-zerogpu | Direct BF16 inference on ZeroGPU xlarge; separate from the NVFP4 endpoint |
| Cosmos Reason2 specialist | https://huggingface.co/spaces/gulle1155/Cosmos-Reason2-8B | Direct BF16 inference on ZeroGPU large |

Hunyuan uses `hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v`, the Diffusers format of the Studio's HunyuanVideo 1.5 model family. Its custom handler repository is `gulle1155/studio-hunyuan-video-1-5-endpoint` (private).

The Hunyuan endpoint accepts root POST JSON with `inputs` and `parameters` (seed, num_frames, num_inference_steps), and returns MP4 base64 plus actual output metadata. The Space exposes Gradio `/generate`. Native Studio Settings now provides a hosted preview adapter that saves an MP4 for import. This does not replace the durable render-worker protocol or automate Timeline render submission.

The Nemotron Space now loads `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16` directly on ZeroGPU, using the checked-in app under `spaces/nemotron-3-nano-omni-zerogpu`. Its `/v1/chat/completions` adapter queues the actual `@spaces.GPU` function. This is a different weight format from the separate dedicated NVFP4 endpoint. Direct NVFP4 ZeroGPU hosting remains unqualified. Cosmos has the same Studio API and a separate checked-in app under `spaces/cosmos-reason2-8b-zerogpu`; Cosmos accepts images/video and does not support audio.

Deployment creation, application startup, successful inference, valid media output, and Studio integration are separate qualification stages. Consult live deployment logs for current readiness.

## MCP and repository webhooks

Codex's global `hf-mcp-server` uses `https://huggingface.co/mcp?login` with OAuth. Added and login completed on 2026-10-09.

Studio uses `https://huggingface.co/mcp` with a bearer token. Its hosted connection prefers the protected credential saved in Studio over inherited environment tokens, because private Spaces can return 404 for a rejected credential rather than 401.

All three Space applications launch with `mcp_server=True`. Their MCP URLs are:

- https://gulle1155-hunyuan-video-1-5-zerogpu.hf.space/gradio_api/mcp/
- https://gulle1155-nemotron-3-nano-omni-zerogpu.hf.space/gradio_api/mcp/
- https://gulle1155-cosmos-reason2-8b.hf.space/gradio_api/mcp/

The Nemotron Space requires authenticated access. An earlier check after MCP registration found both Spaces PAUSED, so their MCP URLs returned 503 and live tool discovery was not verified at that time. Previous generation evidence below predates that paused state.

Hub repository-update webhooks require a receiving HTTPS URL. Native Studio Settings can save the URL and protected secret, then create or update a registration. No live webhook was created because no receiving URL was supplied. Watch scope: `space:gulle1155/hunyuan-video-1-5-zerogpu`, `space:gulle1155/nemotron-3-nano-omni-zerogpu`, and `model:gulle1155/studio-hunyuan-video-1-5-endpoint`; domain `repo`. This subscribes to repository changes, not generation completion. A receiver should validate Hugging Face's `X-Webhook-Secret` header. The MCP URL is not a webhook receiver.

## Native Studio usage

1. Open **Settings and cloud > Hugging Face - hosted models, MCP and webhooks**. Saved settings load when the page opens; **Load connections** reloads them.
2. Save a Hugging Face token in the protected credential field, or use the backend machine's `hf auth login` / `EDMG_HF_TOKEN`. Empty password fields preserve saved credentials. Codex OAuth does not automatically authenticate the Studio backend.
3. Select Hub, Hunyuan, Nemotron or Cosmos and choose **Discover MCP tools**. This performs an MCP initialize/session negotiation and tools/list call. It does not execute arbitrary tools or authorize generation.
4. In **AI Director**, choose **Use Hugging Face Nemotron endpoint**, then **Save AI Director settings**. The button selects BF16 for a Space URL and NVFP4 for a dedicated endpoint. Use **Use Cosmos ZeroGPU for Director specialist** to populate the specialist connection, then save AI Director settings. The existing protected HF credential authenticates both. Plans still pass review/apply.
5. Use **Generate and save short Hunyuan MP4** for a 17-frame, 20-step hosted preview. Select a destination before generation. Import the saved video into a project using Studio's existing media workflow.
6. For repo notifications, enter your receiving HTTPS URL and ASCII secret, then **Register or update repository webhook**. The returned ID is persisted so later updates reuse the registration. No public Studio webhook receiver is created automatically.

Backend routes are under `/v1/huggingface`: GET/POST `settings`, GET `mcp/{hub|hunyuan|nemotron|cosmos}/tools`, POST `webhook`, POST `hunyuan/preview`. Endpoint URLs are restricted to HTTPS Hugging Face endpoint or Space hosts before receiving stored credentials; redirects are disabled. Token candidates rejected with 401 are skipped. Successful settings and webhook responses never return credential values.

Live checks through the new Studio router on 2026-10-09: Hub MCP discovery returned HTTP 200 with four Hub tools; Hunyuan MCP discovery returned HTTP 200 with its generation tool; Nemotron Space returned the expected actionable HTTP 503 while unavailable. These are discovery checks, separate from the earlier model-inference smoke evidence below.

## Inference evidence from before the Spaces were paused

- Hunyuan ZeroGPU revision `ac412ca050d946bf96c048e071dbb7a68432aea6`: API generated 9 frames / 2 inference steps in 4.0 seconds, then 17 frames / 20 steps in 35.9 seconds. Runtime reported NVIDIA RTX PRO 6000 Blackwell Server Edition MIG 4g.96gb. Independent PyAV decode read all 17 frames from the second MP4. This qualifies short text-to-video previews only.
- Nemotron Space revision `c128541c7ffa7c60ee4d7c912ad234f659a5f740`: authenticated Gradio `/run_nemotron` returned `Ready.` through the dedicated endpoint. Initial cold start returned 503; the application now retries temporary service errors. This verifies text only, not multimodal analysis or Studio Director planning.
- Hunyuan endpoint handler revision `5fa91a30b7cd36d57842133ec7c9e2eb14263b20`: running; authenticated POST returned HTTP 200, 48,642-byte MP4, 9 frames at 24 fps, generation time 4.58 seconds, NVIDIA RTX PRO 6000 Blackwell Server Edition. Independent PyAV decode read all 9 frames. Initial attempts exposed mismatched torchvision and old PEFT in the managed container; matching Torch packages and PEFT were added explicitly.
- Hunyuan Space revision `6e3e118d278995fc5d22c60260166f4304e7109c` changes only the duration reservation and documentation. After startup and model packing, its API generated another 9-frame MP4 in 5.2 seconds on ZeroGPU. The dynamic reservation is based on the measured previews above.


## Direct ZeroGPU integration verification (2026-10-09)

Native Settings accepts Spaces or dedicated endpoints and includes all three Space MCP connections. Studio's Hunyuan preview adapter uses the Space Gradio queue and fetches the result only from the configured Space host. Director connections attach the protected HF credential to Space requests. Invalid model JSON is reported as a schema failure, rather than an API-token failure.

- Hunyuan: Studio API produced a 9-frame, 832x480 H.264 MP4 at 24 fps using 5 steps. Independent ffprobe and full ffmpeg decode passed. ZeroGPU receipt reported RTX PRO 6000 Blackwell MIG 4g.96gb.
- Cosmos: direct text and uploaded-image requests completed on RTX PRO 6000 Blackwell MIG 2g.48gb. The image response identified the generated blue waveform. A structured specialist response passed schema validation but supplied no substantive evidence; specialist decision quality remains unqualified.
- Nemotron: direct short text completed on RTX PRO 6000 Blackwell MIG 4g.96gb. Director planning initially failed schema validation. The app now requires the published Mamba CUDA kernels because the upstream reference torch fallback warns about degraded numerical accuracy. After rebuilding with CUDA kernels, the Studio Director provider produced a schema-valid scene edit to a glowing blue waveform, preserving the scene ID and exact 0..48000 sample timing. It completed in 58.06 seconds including first-request kernel setup; the Space receipt reported 51.77 seconds and 333 output tokens on RTX PRO 6000 Blackwell MIG 4g.96gb.

These checks qualify short previews and the listed model calls, not a complete hosted full-song render or all Nemotron media modalities. Dedicated endpoint deployment and billing remain separate. Repository webhooks require a real receiving HTTPS service; MCP is not a webhook receiver.

- Final connection checks: Studio MCP discovery returned HTTP 200 for Hub, Hunyuan, Nemotron, and Cosmos. Native Release build passed with zero warnings/errors; the rebuilt EDMG Studio window was launched. Focused backend regressions: 31 passed.
