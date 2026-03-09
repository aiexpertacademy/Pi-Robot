import asyncio
import os
import sys
import logging
from dotenv import load_dotenv
from livekit import api, rtc

load_dotenv()

async def main():
    print("Welcome to Era's Terminal Connection!")
    print("Connecting to the LiveKit Room...")
    
    room = rtc.Room()

    @room.on("data_received")
    def on_data_received(data: rtc.DataPacket):
        # Decode and print messages from the agent
        text = data.data.decode('utf-8')
        print(f"\n[Era]: {text}")
        print("\n> ", end="", flush=True)

    url = os.getenv("LIVEKIT_URL")
    if not url:
        print("Error: LIVEKIT_URL not found in .env")
        return

    # Generate a token for this terminal user
    token = api.AccessToken() \
        .with_identity("terminal-user") \
        .with_name("Terminal User") \
        .with_grants(api.VideoGrants(room_join=True, room="era-room")) \
        .to_jwt()

    await room.connect(url, token)
    print("\nCONNECTED successfully! You can now type messages to Era.")
    print("Type 'quit' or 'exit' to leave.")

    loop = asyncio.get_event_loop()
    
    while True:
        try:
            line = await loop.run_in_executor(None, lambda: input("\n> "))
        except EOFError:
            break
            
        line = line.strip()
        if line.lower() in ["quit", "exit"]:
            break
            
        if line:
            # Publish as a text message on the "chat" topic
            await room.local_participant.publish_data(
                line.encode('utf-8'),
                reliable=True,
                topic="chat"
            )
            # Sometimes agents listen on "lk-chat" or just default.
            await room.local_participant.publish_data(
                line.encode('utf-8'),
                reliable=True,
                topic="lk-chat"
            )

    await room.disconnect()
    print("Disconnected.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    # Using python 3.10+ standard event loop behavior
    asyncio.run(main())
