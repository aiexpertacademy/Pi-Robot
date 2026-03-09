import { useState, useEffect } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useVoiceAssistant,
  useTrackVolume,
  BarVisualizer,
} from "@livekit/components-react";

function RobotFace() {
  const { state, audioTrack } = useVoiceAssistant();
  const volume = useTrackVolume(audioTrack);
  const [isBlinking, setIsBlinking] = useState(false);
  const [dots, setDots] = useState("");

  const idleScale = 0.15;
  const maxScale = 1.0;

  // Base mouth size logic
  const mouthScaleY = state === "speaking" ? Math.max(idleScale, volume * maxScale) : idleScale;
  const mouthScaleX = state === "speaking" ? Math.min(1.0, 0.4 + (volume * 0.6)) : 0.4;

  useEffect(() => {
    const blinkInterval = setInterval(() => {
      setIsBlinking(true);
      setTimeout(() => setIsBlinking(false), 150);
    }, 3000 + Math.random() * 4000);
    return () => clearInterval(blinkInterval);
  }, []);

  // Animating dots for thinking
  useEffect(() => {
    const dotsInterval = setInterval(() => {
      setDots(d => (d.length >= 3 ? "" : d + "."));
    }, 400);
    return () => clearInterval(dotsInterval);
  }, []);

  return (
    <div className="flex flex-col items-center justify-center w-full h-screen gap-8">
      {/* Container */}
      <div className="relative w-64 h-64 bg-slate-800 rounded-full flex flex-col items-center justify-center shadow-[0_0_60px_rgba(31,213,249,0.15)] border border-slate-700 overflow-hidden">

        {/* Glow */}
        <div
          className="absolute inset-0 bg-blue-500/20 transition-opacity duration-500 ease-in-out"
          style={{ opacity: state === "listening" || state === "speaking" ? 1 : 0 }}
        />

        {/* Eyes Grouping Fix */}
        <div className="relative flex justify-center gap-12 mt-8 mb-6 w-full z-10 text-cyan-400">
          <div
            className="w-8 h-12 bg-current rounded-full transition-transform duration-100 ease-in-out shadow-[0_0_15px_currentColor]"
            style={{ transform: `scaleY(${isBlinking ? 0.1 : 1})` }}
          />
          <div
            className="w-8 h-12 bg-current rounded-full transition-transform duration-100 ease-in-out shadow-[0_0_15px_currentColor]"
            style={{ transform: `scaleY(${isBlinking ? 0.1 : 1})` }}
          />
        </div>

        {/* Mouth */}
        <div className="relative z-10 h-16 w-32 flex items-center justify-center -translate-y-2">
          <div
            className="bg-cyan-400 rounded-full transition-transform duration-75 ease-out shadow-[0_0_15px_currentColor]"
            style={{
              width: "100%",
              height: "100%",
              transform: `scale(${mouthScaleX}, ${mouthScaleY})`
            }}
          />
        </div>
      </div>

      {/* Indicator */}
      <div className="flex flex-col items-center h-24 gap-4">
        <div className="text-slate-400 font-mono text-sm tracking-widest uppercase">
          {state === "disconnected" ? `CONNECTING${dots}`
            : state === "connecting" ? `CONNECTING${dots}`
              : state === "listening" ? "LISTENING"
                : state === "thinking" ? `THINKING${dots}`
                  : state === "speaking" ? "SPEAKING"
                    : "READY"}
        </div>

        {/* Subtle audio visualizer underneath the face */}
        <div className="flex h-12 w-48 opacity-30 items-end justify-center">
          {state === "speaking" && audioTrack && (
            <BarVisualizer
              state={state}
              options={{ minHeight: 4 }}
              trackRef={audioTrack}
              barCount={9}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// Main App
export default function App() {
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const fetchToken = async () => {
      try {
        const response = await fetch("http://localhost:8082/getToken");
        if (response.ok) {
          const data = await response.text();
          setToken(data);
        }
      } catch (err) { }
    };

    fetchToken();
    const interval = setInterval(() => {
      if (!token) fetchToken();
    }, 2000);
    return () => clearInterval(interval);
  }, [token]);

  if (!token) {
    return (
      <div className="flex flex-col items-center justify-center h-screen w-full bg-slate-900 text-slate-400 font-mono">
        <div className="animate-pulse mb-4">Waking up Era...</div>
        <div className="text-sm opacity-50">Waiting for agent.py backend</div>
      </div>
    );
  }

  return (
    <LiveKitRoom
      serverUrl={import.meta.env.VITE_LIVEKIT_URL}
      token={token}
      connect={true}
      audio={true}
      video={false}
      className="w-full h-full"
    >
      <RobotFace />
      <RoomAudioRenderer />
    </LiveKitRoom>
  );
}
