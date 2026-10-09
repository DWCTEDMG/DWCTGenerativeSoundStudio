---
name: gulle1155-hunyuan-video-1-5-zerogpu
description: Use the gulle1155/hunyuan-video-1-5-zerogpu Gradio Space via API. Provides Python, JavaScript, and cURL usage examples.
---

# gulle1155/hunyuan-video-1-5-zerogpu

This skill describes how to use the gulle1155/hunyuan-video-1-5-zerogpu Gradio Space programmatically.

## API Endpoints

### `/generate`

**Parameters:**

- `prompt` [Textbox]: `str`, default: `A glowing waveform floating above a dark stage, slow cinematic camera movement`
- `seed` [Number]: `int`, default: `42`
- `frames` [Dropdown]: `Literal['9', '17', '25', '33']`, default: `17`
- `steps` [Slider]: `float`, default: `20`

**Returns:**

- `Preview` [Video]: `filepath`
- `Generation details` [Textbox]: `str`

**Python:**

```python
from gradio_client import Client

client = Client("gulle1155/hunyuan-video-1-5-zerogpu")
result = client.predict(
	prompt="A glowing waveform floating above a dark stage, slow cinematic camera movement",
	seed=42,
	frames="17",
	steps=20,
	api_name="/generate",
)
print(result)
```

**JavaScript:**

```javascript
import { Client } from "@gradio/client";

const client = await Client.connect("gulle1155/hunyuan-video-1-5-zerogpu");
const result = await client.predict("/generate", {
		prompt: "A glowing waveform floating above a dark stage, slow cinematic camera movement",
		seed: 42,
		frames: "17",
		steps: 20,
});

console.log(result.data);
```

**cURL:**

```bash
curl -X POST https://gulle1155-hunyuan-video-1-5-zerogpu.hf.space/call/v2/generate -s -H "Content-Type: application/json" \
  -d '{"prompt": "A glowing waveform floating above a dark stage, slow cinematic camera movement", "seed": 42, "frames": "17", "steps": 20}' \
  | awk -F'"' '{ print $4}' \
  | read EVENT_ID; curl -N https://gulle1155-hunyuan-video-1-5-zerogpu.hf.space/call/generate/$EVENT_ID
```
