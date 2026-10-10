---
name: gulle1155-Cosmos-Reason2-8B
description: Use the gulle1155/Cosmos-Reason2-8B Gradio Space via API. Provides Python, JavaScript, and cURL usage examples.
---

# gulle1155/Cosmos-Reason2-8B

This skill describes how to use the gulle1155/Cosmos-Reason2-8B Gradio Space programmatically.

## API Endpoints

### `/run_cosmos`

**Parameters:**

- `prompt` [Textbox]: `str`, default: `Reply with exactly: Ready`
- `image` [Image]: `filepath`, default: `None`
- `audio` [Audio]: `filepath`, default: `None`
- `video` [Video]: `filepath`, default: `None`
- `mode` [Radio]: `Literal['Instruct', 'Thinking']`, default: `Instruct`
- `use_audio_in_video` [Checkbox]: `bool`, default: `False`
- `max_tokens` [Slider]: `float`, default: `256`
- `reasoning_budget` [Number]: `float`, default: `1024`
- `temperature` [Number]: `float`, default: `0.2`
- `top_p` [Number]: `float`, default: `0.95`
- `base_url_override` [Textbox]: `str`, default: ``
- `model_override` [Textbox]: `str`, default: ``

**Returns:**

- `Response` [Textbox]: `str`

**Python:**

```python
from gradio_client import Client, handle_file

client = Client("gulle1155/Cosmos-Reason2-8B")
result = client.predict(
	prompt="Reply with exactly: Ready",
	image=None,
	audio=None,
	video=None,
	mode="Instruct",
	use_audio_in_video=False,
	max_tokens=256,
	reasoning_budget=1024,
	temperature=0.2,
	top_p=0.95,
	base_url_override="",
	model_override="",
	api_name="/run_cosmos",
)
print(result)
```

**JavaScript:**

```javascript
import { Client, handle_file } from "@gradio/client";

const response_0 = await fetch("https://raw.githubusercontent.com/gradio-app/gradio/main/test/test_files/bus.png");
const exampleImage = await response_0.blob();
const response_1 = await fetch("https://github.com/gradio-app/gradio/raw/main/test/test_files/audio_sample.wav");
const exampleAudio = await response_1.blob();
const response_2 = await fetch("https://github.com/gradio-app/gradio/raw/main/gradio/media_assets/videos/world.mp4");
const exampleVideo = await response_2.blob();

const client = await Client.connect("gulle1155/Cosmos-Reason2-8B");
const result = await client.predict("/run_cosmos", {
		prompt: "Reply with exactly: Ready",
		image: handle_file(exampleImage),
		audio: handle_file(exampleAudio),
		video: handle_file(exampleVideo),
		mode: "Instruct",
		use_audio_in_video: false,
		max_tokens: 256,
		reasoning_budget: 1024,
		temperature: 0.2,
		top_p: 0.95,
		base_url_override: "",
		model_override: "",
});

console.log(result.data);
```

**cURL:**

```bash
FILE_PATH=$(curl -s -X POST https://gulle1155-cosmos-reason2-8b.hf.space/upload -F 'files=@/path/to/your/file' | tr -d '[]" ')

curl -X POST https://gulle1155-cosmos-reason2-8b.hf.space/call/v2/run_cosmos -s -H "Content-Type: application/json" \
  -d '{"prompt": "Reply with exactly: Ready", "image": {"path": "'$FILE_PATH'", "meta": {"_type": "gradio.FileData"}}, "audio": {"path": "'$FILE_PATH'", "meta": {"_type": "gradio.FileData"}}, "video": {"path": "'$FILE_PATH'", "meta": {"_type": "gradio.FileData"}}, "mode": "Instruct", "use_audio_in_video": false, "max_tokens": 256, "reasoning_budget": 1024, "temperature": 0.2, "top_p": 0.95, "base_url_override": "", "model_override": ""}' \
  | awk -F'"' '{ print $4}' \
  | read EVENT_ID; curl -N https://gulle1155-cosmos-reason2-8b.hf.space/call/run_cosmos/$EVENT_ID
```

### `/chat`

**Parameters:**

- `messages` [Json]: `str | float | bool | list | dict` (required)
- `max_tokens` [Slider]: `float`, default: `256`
- `thinking` [Checkbox]: `bool`, default: `False`

**Returns:**

- `Response` [Textbox]: `str`

**Python:**

```python
from gradio_client import Client

client = Client("gulle1155/Cosmos-Reason2-8B")
result = client.predict(
	messages={"foo": "bar"},
	max_tokens=256,
	thinking=False,
	api_name="/chat",
)
print(result)
```

**JavaScript:**

```javascript
import { Client } from "@gradio/client";

const client = await Client.connect("gulle1155/Cosmos-Reason2-8B");
const result = await client.predict("/chat", {
		messages: {"foo": "bar"},
		max_tokens: 256,
		thinking: false,
});

console.log(result.data);
```

**cURL:**

```bash
curl -X POST https://gulle1155-cosmos-reason2-8b.hf.space/call/v2/chat -s -H "Content-Type: application/json" \
  -d '{"messages": {"foo": "bar"}, "max_tokens": 256, "thinking": false}' \
  | awk -F'"' '{ print $4}' \
  | read EVENT_ID; curl -N https://gulle1155-cosmos-reason2-8b.hf.space/call/chat/$EVENT_ID
```

