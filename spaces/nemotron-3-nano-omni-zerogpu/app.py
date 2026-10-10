import spaces
import os, json, time, uuid
import torch
import gradio as gr
import httpx
import numpy as np
from PIL import Image
from fastapi import APIRouter, Request, HTTPException
from transformers import AutoModelForCausalLM, AutoProcessor, AutoTokenizer

MODEL_ID = "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16"
REVISION = "e5e9932441de940c9a62185c870ea5bcd4cd24e2"
print("Loading direct Nemotron BF16 for ZeroGPU xlarge", flush=True)
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=REVISION, trust_remote_code=True)
processor = AutoProcessor.from_pretrained(MODEL_ID, revision=REVISION, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(MODEL_ID, revision=REVISION, trust_remote_code=True, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True, attn_implementation="eager").eval().to("cuda")
print("Nemotron loaded; ZeroGPU placement complete", flush=True)

def infer(messages, max_tokens=256, thinking=False, image=None, audio=None, video=None):
    started = time.perf_counter()
    # NVIDIA's remote model retains the pre-5.19 masking argument names.
    # Adapt names only; keep Transformers' original causal-mask implementation.
    import sys, inspect
    remote_module = sys.modules[model.language_model.__class__.__module__]
    # Use the published CUDA kernels: the reference torch Mamba path changes numerics.
    if not remote_module.is_fast_path_available:
        from kernels import get_kernel
        from transformers.integrations.hub_kernels import resolve_internal_import
        conv = get_kernel("kernels-community/causal-conv1d", version=1)
        mamba = get_kernel("kernels-community/mamba-ssm", version=1)
        remote_module.causal_conv1d_fn = conv.causal_conv1d_fn
        remote_module.causal_conv1d_update = conv.causal_conv1d_update
        remote_module.selective_state_update = resolve_internal_import(mamba, "ops.triton.selective_state_update.selective_state_update")
        remote_module.mamba_chunk_scan_combined = resolve_internal_import(mamba, "ops.triton.ssd_combined.mamba_chunk_scan_combined")
        remote_module.mamba_split_conv1d_scan_combined = resolve_internal_import(mamba, "ops.triton.ssd_combined.mamba_split_conv1d_scan_combined")
        remote_module.is_fast_path_available = True
    cache_class = remote_module.NemotronHHybridDynamicCache
    if not hasattr(cache_class, 'get_query_offset'):
        from transformers.cache_utils import Cache
        cache_class.get_query_offset = Cache.get_query_offset
    original_mask = remote_module.create_causal_mask
    parameters = inspect.signature(original_mask).parameters
    if 'inputs_embeds' in parameters and 'input_embeds' not in parameters:
        def compatible_mask(**kwargs):
            if 'input_embeds' in kwargs:
                kwargs['inputs_embeds'] = kwargs.pop('input_embeds')
            if 'cache_position' not in parameters:
                kwargs.pop('cache_position', None)
            return original_mask(**kwargs)
        remote_module.create_causal_mask = compatible_mask
    if not torch.cuda.is_available():
        raise RuntimeError("ZeroGPU did not allocate CUDA; refusing CPU inference")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list")
    if len(json.dumps(messages)) > 100000:
        raise ValueError("Shorten the Director context to 100000 characters")
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=thinking)
    media = {}
    if image: media['images'] = Image.open(image).convert('RGB')
    if audio: media['audio'] = audio
    if video:
        import av
        frames=[]
        with av.open(video) as container:
            stream=container.streams.video[0]
            interval=max(1, int(float(stream.average_rate or 24)))
            for index,frame in enumerate(container.decode(video=0)):
                if index % interval == 0: frames.append(frame.to_ndarray(format='rgb24'))
                if len(frames)==8: break
        if not frames: raise ValueError("Video contains no decodable frames")
        if len(frames)%2: frames.append(frames[-1])
        media['videos'] = np.stack(frames)
    inputs=processor(text=text, return_tensors='pt', **media)
    allowed={'input_ids','attention_mask','pixel_values','pixel_values_videos','sound_clips','sound_length'}
    inputs={k:(v.to('cuda') if isinstance(v,torch.Tensor) else v) for k,v in inputs.items() if k in allowed}
    with torch.inference_mode():
        output=model.generate(**inputs,max_new_tokens=max(1,min(int(max_tokens),2048)),do_sample=False,pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
    content=tokenizer.decode(output[0,inputs['input_ids'].shape[-1]:],skip_special_tokens=True)
    print(json.dumps({'provider':'huggingface_zerogpu','model':MODEL_ID,'device':torch.cuda.get_device_name(),'elapsed_s':round(time.perf_counter()-started,2),'output_tokens':int(output.shape[-1]-inputs['input_ids'].shape[-1])}),flush=True)
    return content

@spaces.GPU(size='xlarge',duration=120)
def chat(messages: list, max_tokens: int = 256, thinking: bool = False) -> str:
    """Generate a response with Nemotron Omni BF16 directly on a ZeroGPU CUDA allocation."""
    return infer(messages,max_tokens,thinking)

@spaces.GPU(size='xlarge',duration=120)
def run_nemotron(prompt: str, image: str | None=None, audio: str | None=None, video: str | None=None, mode: str='Instruct', use_audio_in_video: bool=False, max_tokens: int=256, reasoning_budget: int=1024, temperature: float=0.2, top_p: float=0.95, base_url_override: str='', model_override: str='') -> str:
    """Analyze supplied text or media using Nemotron Omni BF16 directly on ZeroGPU; no dedicated endpoint is called."""
    markers=('<image>\n' if image else '')+('<audio>\n' if audio else '')+('<video>\n' if video else '')
    return infer([{'role':'user','content':markers+prompt}],max_tokens,mode=='Thinking',image,audio,video)

with gr.Blocks(title='Nemotron Omni â€” direct ZeroGPU') as demo:
    gr.Markdown('# Nemotron Omni â€” direct ZeroGPU\nRuns NVIDIA Nemotron Omni **BF16** on an xlarge ZeroGPU allocation. No dedicated endpoint or NVIDIA API is used. This is the BF16 weight variant, not NVFP4. Upload short media; video samples up to eight frames. Studio OpenAI base URL: `/v1`.')
    prompt=gr.Textbox(value='Reply with exactly: Ready',label='Prompt',lines=5)
    image=gr.Image(type='filepath',label='Image')
    audio=gr.Audio(type='filepath',label='Audio')
    video=gr.Video(label='Video')
    mode=gr.Radio(['Instruct','Thinking'],value='Instruct',label='Mode')
    tokens=gr.Slider(16,2048,value=256,step=16,label='Maximum output tokens')
    response=gr.Textbox(label='Response',lines=12)
    button=gr.Button('Run Nemotron on ZeroGPU')
    button.click(run_nemotron,[prompt,image,audio,video,mode,gr.Checkbox(False,visible=False),tokens,gr.Number(1024,visible=False),gr.Number(0.2,visible=False),gr.Number(0.95,visible=False),gr.Textbox('',visible=False),gr.Textbox('',visible=False)],response,api_name='run_nemotron')
    messages=gr.JSON(visible=False)
    api_button=gr.Button(visible=False)
    api_button.click(chat,[messages,tokens,gr.Checkbox(False,visible=False)],response,api_name='chat')

app=APIRouter()
@app.get('/v1/models')
def models():
    return {'object':'list','data':[{'id':MODEL_ID,'object':'model','owned_by':'nvidia'}]}
@app.post('/v1/chat/completions')
async def completion(request: Request):
    body=await request.json()
    if body.get('stream'): raise HTTPException(400,'Use stream=false for this ZeroGPU adapter')
    if body.get('model') not in (None,MODEL_ID): raise HTTPException(400,'This Space serves '+MODEL_ID)
    headers={k:v for k,v in request.headers.items() if k.lower() in ('authorization','x-zerogpu-token','x-ip-token','x-forwarded-for')}
    async with httpx.AsyncClient(timeout=300) as client:
        r=await client.post('http://127.0.0.1:7860/gradio_api/call/chat',json={'data':[body.get('messages'),max(16,min(int(body.get('max_tokens',256)),2048)),False]},headers=headers)
        if r.status_code!=200: raise HTTPException(502,'ZeroGPU queue submission failed: '+r.text[:300])
        event=r.json()['event_id']
        async with client.stream('GET','http://127.0.0.1:7860/gradio_api/call/chat/'+event,headers=headers) as result:
            kind=''
            async for line in result.aiter_lines():
                if line.startswith('event:'): kind=line[6:].strip()
                if line.startswith('data:') and kind=='error': raise HTTPException(503,'ZeroGPU generation failed: '+line[5:][:400])
                if line.startswith('data:') and kind=='complete':
                    content=json.loads(line[5:])[0]
                    return {'id':'chatcmpl-'+uuid.uuid4().hex,'object':'chat.completion','created':int(time.time()),'model':MODEL_ID,'choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':'stop'}]}
    raise HTTPException(502,'ZeroGPU returned no completed response')
if __name__=='__main__':
    demo.queue(default_concurrency_limit=1).launch(mcp_server=True,ssr_mode=False,prevent_thread_lock=True)
    demo.app.include_router(app)
    demo.block_thread()
