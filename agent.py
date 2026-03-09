import asyncio
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from dotenv import load_dotenv
from livekit import api

from livekit.agents import AutoSubscribe, JobContext, JobProcess, WorkerOptions, cli, llm
from livekit.agents import Agent, AgentSession
from livekit.plugins import deepgram, openai, silero, elevenlabs

load_dotenv()
logger = logging.getLogger("voice-agent")

def prewarm(proc: JobProcess):
    # Preload Silero VAD into memory to reduce first-turn latency
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    # Connect to the room first
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Initialize the Agent with instructions
    agent = Agent(
        instructions=(
            "You are Era, a fast, responsive, and witty voice assistant. "
            "You understand both Hindi and English perfectly. "
            "If the user speaks in Hindi or Hinglish, always respond back in completely natural spoken Hindi. "
            "Keep your responses concise and conversational. Do not use complex formatting."
        )
    )

    # Initialize the Voice Session using the plugins
    session = AgentSession(
        stt=deepgram.STT(language="hi"),
        llm=openai.LLM(
            model="gemini-2.5-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=os.environ.get("GOOGLE_API_KEY")
        ),
        tts=elevenlabs.TTS(),
        vad=ctx.proc.userdata["vad"],
    )

    # Start the session with the room
    await session.start(agent=agent, room=ctx.room)

    # Wait for the first user to publish an audio track, then greet them
    participant = await ctx.wait_for_participant()
    logger.info(f"Connected with user: {participant.identity}")

    # Speak initial greeting
    session.say("Hello there! My name is Era. I am ready to chat. How can I help you today?", allow_interruptions=True)

# --- Internal Token Server for the UI ---
class TokenHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header("Access-Control-Allow-Headers", "X-Requested-With")
        self.end_headers()

    def do_GET(self):
        if self.path == '/getToken':
            # Generate a secure token for the React UI to join automatically
            token = api.AccessToken() \
                .with_identity("raspberry-pi-display") \
                .with_name("Raspberry Pi Display") \
                .with_grants(api.VideoGrants(
                    room_join=True,
                    room="era-room", # specific room for the UI to join
                ))
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(token.to_jwt().encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def start_token_server():
    server = HTTPServer(('localhost', 8082), TokenHandler)
    logger.info("Token server listening on http://localhost:8082/getToken")
    server.serve_forever()


from livekit.agents import WorkerType

if __name__ == "__main__":
    # Start the token server in a background thread so the UI can connect
    threading.Thread(target=start_token_server, daemon=True).start()

    # Start the worker process
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            worker_type=WorkerType.ROOM,
        )
    )
