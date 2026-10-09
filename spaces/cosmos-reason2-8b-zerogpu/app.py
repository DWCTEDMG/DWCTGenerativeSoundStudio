import spaces
import os, json, time, uuid
import torch
import gradio as gr
import httpx
import numpy as np
from PIL import Image
from fastapi import APIRouter, Request, HTTPException
from transformers import Qwen3VLForConditionalGeneration, AutoProcessor, AutoTokenizer

MODEL_ID = "nvidia/Cosmos-Reason2-8B"
REVISION = "a9fae2cf89dc64db96b12860417f0eb403013bb9"
print("Loading direct Cosmos BF16 for ZeroGPU large", flush=True)
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=REVISION, trust_remote_code=True)
processor = AutoProcessor.from_pretrained(MODEL_ID, revision=REVISION, trust_remote_code=True)
model = Qwen3VLForConditionalGeneration.from_pretrained(MODEL_ID, revision=REVISION, trust_remote_code=True, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True, attn_implementation="sdpa").eval().to("cuda")
print("Cosmos loaded; ZeroGPU placement complete", flush=True)

def infer(messages, max_tokens=256, thinking=False, image=None, audio=None, video=None):
    started = time.perf_counter()
    if not torch.cuda.is_available():
        raise RuntimeError("ZeroGPU did not allocate CUDA; refusing CPU inference")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list")
    if len(json.dumps(messages)) > 100000:
        raise ValueError("Shorten the Director context to 100000 characters")
    if image or video or audio:
        messages = [dict(m) for m in messages]
        text = messages[-1]['content'].replace('<image>\n','').replace('<video>\n','').replace('<audio>\n','')
        parts=[]
        if image: parts.append({'type':'image','image':Image.open(image).convert('RGB')})
        if video: parts.append({'type':'video','video':video,'fps':1,'max_frames':8})
        if audio: raise ValueError('Cosmos accepts images and video, not audio')
        parts.append({'type':'text','text':text})
        messages[-1]['content']=parts
    inputs=processor.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt')
    allowed={'input_ids','attention_mask','pixel_values','pixel_values_videos','image_grid_thw','video_grid_thw','second_per_grid_ts'}
    inputs={k:(v.to('cuda') if isinstance(v,torch.Tensor) else v) for k,v in inputs.items() if k in allowed}
    with torch.inference_mode():
        output=model.generate(**inputs,max_new_tokens=max(1,min(int(max_tokens),2048)),do_sample=False,pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
    content=tokenizer.decode(output[0,inputs['input_ids'].shape[-1]:],skip_special_tokens=True)
    print(json.dumps({'provider':'huggingface_zerogpu','model':MODEL_ID,'device':torch.cuda.get_device_name(),'elapsed_s':round(time.perf_counter()-started,2),'output_tokens':int(output.shape[-1]-inputs['input_ids'].shape[-1])}),flush=True)
    return content

@spaces.GPU(size='large',duration=120)
def chat(messages: list, max_tokens: int = 256, thinking: bool = False) -> str:
    """Generate a response with Cosmos Reason2 8B BF16 directly on a ZeroGPU CUDA allocation."""
    return infer(messages,max_tokens,thinking)

@spaces.GPU(size='large',duration=120)
def run_cosmos(prompt: str, image: str | None=None, audio: str | None=None, video: str | None=None, mode: str='Instruct', use_audio_in_video: bool=False, max_tokens: int=256, reasoning_budget: int=1024, temperature: float=0.2, top_p: float=0.95, base_url_override: str='', model_override: str='') -> str:
    """Analyze supplied text or media using Cosmos Reason2 8B BF16 directly on ZeroGPU; no dedicated endpoint is called."""
    markers=('<image>\n' if image else '')+('<audio>\n' if audio else '')+('<video>\n' if video else '')
    return infer([{'role':'user','content':markers+prompt}],max_tokens,mode=='Thinking',image,audio,video)

with gr.Blocks(title='Cosmos Reason2 8B â€” direct ZeroGPU') as demo:
    gr.Markdown('# Cosmos Reason2 8B â€” direct ZeroGPU\nRuns NVIDIA Cosmos Reason2 8B **BF16** on a large ZeroGPU allocation. No dedicated endpoint or NVIDIA API is used. Upload short media; Cosmos accepts image and video inputs; audio is unsupported. Studio OpenAI base URL: `/v1`.')
    prompt=gr.Textbox(value='Reply with exactly: Ready',label='Prompt',lines=5)
    image=gr.Image(type='filepath',label='Image')
    audio=gr.Audio(type='filepath',label='Audio')
    video=gr.Video(label='Video')
    mode=gr.Radio(['Instruct','Thinking'],value='Instruct',label='Mode')
    tokens=gr.Slider(16,2048,value=256,step=16,label='Maximum output tokens')
    response=gr.Textbox(label='Response',lines=12)
    button=gr.Button('Run Cosmos on ZeroGPU')
    button.click(run_cosmos,[prompt,image,audio,video,mode,gr.Checkbox(False,visible=False),tokens,gr.Number(1024,visible=False),gr.Number(0.2,visible=False),gr.Number(0.95,visible=False),gr.Textbox('',visible=False),gr.Textbox('',visible=False)],response,api_name='run_cosmos')
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
