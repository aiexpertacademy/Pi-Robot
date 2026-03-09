import asyncio
import logging
import os
import threading
import time
import math
import cv2
import queue
import numpy as np
from http.server import BaseHTTPRequestHandler, HTTPServer
import serial
from dotenv import load_dotenv

# We wrap Picamera2 in a try-except so this code doesn't immediately crash if run on Windows/Mac for testing.
try:
    from picamera2 import Picamera2
    HAS_PICAMERA = True
except ImportError:
    HAS_PICAMERA = False
    print("Warning: Picamera2 not found. Camera tracking will be disabled (expected if not on Raspberry Pi).")

from livekit import api
from livekit.agents import AutoSubscribe, JobContext, JobProcess, WorkerOptions, cli
from livekit.agents import Agent, AgentSession
from livekit.plugins import deepgram, openai, silero, elevenlabs

load_dotenv()
logger = logging.getLogger("voice-agent")

# --- ROBOT STATE FOR UI ---
# States: IDLE, LISTENING, THINKING, SPEAKING
robot_state = "IDLE"
state_lock = threading.Lock()
emotional_state = "NEUTRAL"
emotional_state_lock = threading.Lock()

# --- ADVANCED TRACKING PARAMETERS ---
PAN_GAIN = 0.03
PAN_DEAD_ZONE_PERCENT = 0.35
DEFAULT_TILT_ANGLE = 90
PAN_SERVO_MIN_ANGLE = 60
PAN_SERVO_MAX_ANGLE = 120
CENTERING_TOLERANCE = 2

# --- DISPLAY PARAMETERS ---
CAMERA_OVERLAY_WIDTH = 192
CAMERA_OVERLAY_HEIGHT = 144

# Provide globals for the camera worker
latest_frame = None
frame_lock = threading.Lock()

# ---------------------------------------------------------------------------------
# HARDWARE SETUP (Arduino and Camera)
# ---------------------------------------------------------------------------------

def setup_servos():
    try: 
        arduino_connection = serial.Serial('/dev/ttyUSB0', 9600, timeout=1)
        time.sleep(2)
        print("Arduino connected successfully.")
        return arduino_connection
    except serial.SerialException as e: 
        print(f"Warning: Could not connect to Arduino. Error: {e}")
        return None

def send_servo_angles(conn, pan, tilt):
    if conn and conn.is_open: 
        conn.write(f"{int(pan)},{int(tilt)}\n".encode('utf-8'))

def camera_worker(picam2):
    global latest_frame
    while True:
        try:
            frame = picam2.capture_array()
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            with frame_lock: 
                latest_frame = frame
        except Exception as e:
            time.sleep(1)
        time.sleep(0.03)

# ---------------------------------------------------------------------------------
# OPENCV DRAWING FUNCTIONS
# ---------------------------------------------------------------------------------

def draw_eyes(canvas, state, person_center, emotion):
    h, w, _ = canvas.shape
    eye_left_center = (int(w*0.35), int(h*0.4))
    eye_right_center = (int(w*0.65), int(h*0.4))
    eye_radius = int(w*0.1)
    pupil_radius = int(eye_radius*0.4)
    sclera_color = (255,255,255)
    pupil_color = (255,192,0)
    
    cv2.circle(canvas, eye_left_center, eye_radius, sclera_color, -1)
    cv2.circle(canvas, eye_right_center, eye_radius, sclera_color, -1)
    
    pupil_offset_x, pupil_offset_y = 0, 0
    max_pupil_offset = eye_radius - pupil_radius
    
    if person_center: 
        target_x, target_y = person_center
        pupil_offset_x = (target_x / w - 0.5) * 2.5
        pupil_offset_y = (target_y / h - 0.5) * 2.5
    elif state == "THINKING": 
        pupil_offset_x, pupil_offset_y = -0.8, -0.8
    else: 
        t = time.time()
        pupil_offset_x = math.sin(t * 0.7) * 0.6
        pupil_offset_y = math.cos(t * 0.5) * 0.6
        
    pupil_offset_x = np.clip(pupil_offset_x * max_pupil_offset, -max_pupil_offset, max_pupil_offset)
    pupil_offset_y = np.clip(pupil_offset_y * max_pupil_offset, -max_pupil_offset, max_pupil_offset)
    
    current_pupil_radius = int(pupil_radius * 1.3) if state == "LISTENING" else pupil_radius
    
    final_pupil_left = (int(eye_left_center[0] + pupil_offset_x), int(eye_left_center[1] + pupil_offset_y))
    final_pupil_right = (int(eye_right_center[0] + pupil_offset_x), int(eye_right_center[1] + pupil_offset_y))
    
    cv2.circle(canvas, final_pupil_left, current_pupil_radius, pupil_color, -1)
    cv2.circle(canvas, final_pupil_right, current_pupil_radius, pupil_color, -1)

def draw_mouth(canvas, state, emotion):
    h, w, _ = canvas.shape
    mouth_center = (int(w*0.5), int(h*0.75))
    mouth_width = int(w*0.25)
    mouth_height_max = int(h*0.1)
    line_color = (255,255,255)
    
    if state == "SPEAKING": 
        t = time.time()
        mouth_h = abs(math.sin(t*20)*0.6+math.sin(t*35)*0.4)*mouth_height_max
        cv2.ellipse(canvas, mouth_center, (mouth_width//2, int(max(5,mouth_h))//2), 0,0,360, line_color, -1)
    elif state == "THINKING": 
        cv2.circle(canvas, mouth_center, int(mouth_height_max*0.2), line_color, -1)
    elif emotion == "HAPPY": 
        cv2.ellipse(canvas, mouth_center, (mouth_width//2, mouth_height_max//2), 0,0,180, line_color, -1)
    elif emotion == "SAD": 
        cv2.ellipse(canvas, mouth_center, (mouth_width//2, mouth_height_max//2), 0,180,360, line_color, -1)
    elif emotion == "CONFUSED": 
        cv2.line(canvas, (mouth_center[0]-mouth_width//2, mouth_center[1]), (mouth_center[0]+mouth_width//2, mouth_center[1]), line_color, 8)
    else: 
        cv2.ellipse(canvas, mouth_center, (mouth_width//2, mouth_height_max//3), 0,0,180, line_color, 8)

def draw_robot_face(frame_shape, state, person_center):
    h, w, _ = frame_shape
    target_w = int(h * 16 / 9)
    fullscreen_canvas = np.zeros((h, target_w, 3), dtype="uint8")
    face_canvas = np.zeros((h, w, 3), dtype="uint8")
    
    with emotional_state_lock: 
        current_emotion = emotional_state
        
    draw_eyes(face_canvas, state, person_center, current_emotion)
    draw_mouth(face_canvas, state, current_emotion)
    
    x_offset = (target_w - w) // 2
    fullscreen_canvas[:, x_offset:x_offset + w] = face_canvas
    return fullscreen_canvas

# ---------------------------------------------------------------------------------
# BACKGROUND VISUAL THREAD
# ---------------------------------------------------------------------------------

def visual_tracking_loop():
    global latest_frame
    
    print("Starting visual hardware system...")
    
    face_cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    face_cascade = cv2.CascadeClassifier(face_cascade_path)
    
    arduino = setup_servos()
    current_pan_angle = 90
    send_servo_angles(arduino, 90, DEFAULT_TILT_ANGLE)

    window_name = "Era Robot View"
    cv2.namedWindow(window_name, cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    
    # Fallback to an empty black frame if no camera is available
    fallback_frame = np.zeros((480, 640, 3), dtype="uint8")

    try:
        while True:
            with frame_lock:
                if latest_frame is None:
                     frame = fallback_frame.copy()
                else:
                     frame = latest_frame.copy()

            H, W, _ = frame.shape
            SCREEN_CENTER_X, SCREEN_CENTER_Y = W//2, H//2
            
            gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            face_locations = face_cascade.detectMultiScale(
                gray_frame,
                scaleFactor=1.1,
                minNeighbors=3,
                minSize=(70, 70)
            )
            
            person_center = None
            if len(face_locations) > 0:
                faces_with_areas = [(x, y, w, h, w*h) for (x, y, w, h) in face_locations]
                largest_face = max(faces_with_areas, key=lambda item: item[4])
                x, y, w, h, _ = largest_face
                person_center = (int(x + w/2), int(y + h/2))

            # --- Servo tracking ---
            if person_center:
                error_x = person_center[0] - SCREEN_CENTER_X
                if abs(error_x) > (W * PAN_DEAD_ZONE_PERCENT / 2):
                    current_pan_angle = max(PAN_SERVO_MIN_ANGLE, min(PAN_SERVO_MAX_ANGLE, current_pan_angle - error_x*PAN_GAIN))
                    send_servo_angles(arduino, current_pan_angle, DEFAULT_TILT_ANGLE)
                elif abs(current_pan_angle - 90) > CENTERING_TOLERANCE:
                    current_pan_angle += 0.5 if current_pan_angle < 90 else -0.5
                    send_servo_angles(arduino, current_pan_angle, DEFAULT_TILT_ANGLE)
            elif abs(current_pan_angle - 90) > CENTERING_TOLERANCE:
                current_pan_angle += 0.5 if current_pan_angle < 90 else -0.5
                send_servo_angles(arduino, current_pan_angle, DEFAULT_TILT_ANGLE)

            # Draw the face based on the LiveKit synced global state!
            with state_lock:
                render_state = robot_state
                
            display_canvas = draw_robot_face(frame.shape, render_state, person_center)
            display_H, display_W, _ = display_canvas.shape
            
            # Draw the PIP of the camera feedback
            if latest_frame is not None:
                small_camera_feed = cv2.resize(frame, (CAMERA_OVERLAY_WIDTH, CAMERA_OVERLAY_HEIGHT))
                display_canvas[display_H-CAMERA_OVERLAY_HEIGHT:display_H, display_W-CAMERA_OVERLAY_WIDTH:display_W] = small_camera_feed
            
            inverted_display = cv2.flip(display_canvas, 0)
            cv2.imshow(window_name, inverted_display)
            
            if cv2.waitKey(1) & 0xFF == ord('q'): 
                break

    finally:
        print("Shutting down... Centering servos.")
        send_servo_angles(arduino, 90, DEFAULT_TILT_ANGLE)
        if arduino: 
            arduino.close()
        cv2.destroyAllWindows()


# ---------------------------------------------------------------------------------
# LIVEKIT AGENT LOGIC
# ---------------------------------------------------------------------------------

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    global robot_state
    
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    agent = Agent(
        instructions=(
            "You are Era, a fast, responsive, and witty voice assistant. "
            "You understand both Hindi and English perfectly. "
            "If the user speaks in Hindi or Hinglish, always respond back in completely natural spoken Hindi. "
            "Keep your responses concise and conversational. Do not use complex formatting. Do not use asterisks or markdown."
        )
    )

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

    # --- Sync LiveKit Events to the OpenCV Face State ---
    @agent.on("agent_started_speaking")
    def on_agent_started_speaking():
        global robot_state
        with state_lock:
            robot_state = "SPEAKING"

    @agent.on("agent_stopped_speaking")
    def on_agent_stopped_speaking():
        global robot_state
        with state_lock:
            robot_state = "IDLE"

    @session.on("user_speech_committed")
    def on_user_speech_committed(msg):
        global robot_state
        with state_lock:
            robot_state = "THINKING"

    @session.on("user_started_speaking")
    def on_user_started_speaking():
        global robot_state
        with state_lock:
            robot_state = "LISTENING"

    # Start the session with the room
    await session.start(agent=agent, room=ctx.room)

    participant = await ctx.wait_for_participant()
    logger.info(f"Connected with user: {participant.identity}")

    with state_lock:
        robot_state = "SPEAKING"
    session.say("Hello there! My name is Era. I am ready to chat. How can I help you today?", allow_interruptions=True)
    with state_lock:
        robot_state = "IDLE"

# ---------------------------------------------------------------------------------
# BOOTSTRAP
# ---------------------------------------------------------------------------------

if __name__ == "__main__":
    
    # 1. Start the camera feed directly
    if HAS_PICAMERA:
        print("Initializing Picamera...")
        picam2 = Picamera2()
        picam2.configure(picam2.create_preview_configuration(main={"size": (640, 480)}))
        picam2.start()
        time.sleep(2)
        threading.Thread(target=camera_worker, args=(picam2,), daemon=True).start()
    else:
        print("Initializing Standard Webcam (Testing Mode)...")
        cap = cv2.VideoCapture(0) # Open default webcam
        
        def fallback_camera_worker():
            global latest_frame
            while True:
                ret, frame = cap.read()
                if ret:
                    with frame_lock:
                        latest_frame = frame
                time.sleep(0.03)

        threading.Thread(target=fallback_camera_worker, daemon=True).start()

    # 2. Start the visual tracking UI logic 
    threading.Thread(target=visual_tracking_loop, daemon=True).start()

    # 3. Start the LiveKit Voice Agent worker process
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )
