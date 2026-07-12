from dotenv import load_dotenv

load_dotenv()
import os
import asyncio
from anthropic import AsyncAnthropic

agent = AsyncAnthropic(
    base_url= os.environ.get("ANTHROPIC_BASE_URL"),
    api_key= os.environ.get("ANTHROPIC_API_KEY"),
)



async def send() -> None:
    inp = input()
    create_params = {
        "model":os.environ.get('MINI_CLAUDE_MODEL'),
        "max_tokens":1024,
        "messages":[{
            "role":"user",
            "content":inp.strip()
        }]
    }
    async with agent.messages.stream(**create_params) as stream:
        async for event in stream:
            if event.type == 'message_start':
                print(f"event message_start")
            if event.type == 'content_block_start':
                print(f"event content_block_start: {event.content_block}")
            if event.type == 'content_block_delta':
                delta = event.delta
                if hasattr(delta, 'thinking'):
                    print(f"delta thinking: {delta.thinking}")
                if hasattr(delta, 'text'):
                    print(delta.text, end="", flush=True)
            if event.type == 'message_stop':
                print(f"\n event message_stop")


    # response = await agent.messages.create(
    #     model=os.environ.get('MINI_CLAUDE_MODEL'),
    #     messages=[
    #         {"role":"user","content":inp.strip()}
    #     ],
    #     max_tokens=1024
    # )
    # print(response.content)
    # for c in response.content:
    #     if c.type == 'text':
    #         print(c.text)


asyncio.run(send())