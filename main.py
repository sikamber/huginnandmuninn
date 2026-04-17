from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai import Agent

app = FastAPI()
agent = Agent("anthropic:claude-sonnet-4-6")


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
async def chat(request: ChatRequest):
    async def stream():
        async with agent.run_stream(request.message) as result:
            async for chunk in result.stream_text(delta=True):
                yield chunk

    return StreamingResponse(stream(), media_type="text/plain")
