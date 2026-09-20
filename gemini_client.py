import asyncio
import os
import time
from typing import Callable, Optional, Dict, Any
from google import genai
from google.genai import types
from config import config
from tools import get_jarvis_tools, execute_tool_call

class GeminiLiveClient:
    def __init__(self, initial_mode: str = "command"):
        self.client = genai.Client(
            api_key=config.api_key,
            http_options={'api_version': 'v1alpha'}
        )
        self.session = None
        self._session_context = None
        self._connected = False
        self._lock = asyncio.Lock()
        self.active_mode = initial_mode
        self._last_activity_time = 0.0
        self._needs_reconnect = False
        self.on_tool_executed: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], None]] = None

    def _create_config(self) -> types.LiveConnectConfig:
        voice_cfg = None
        if config.voice_name:
            voice_cfg = types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.voice_name)
            )

        speech_cfg = None
        if voice_cfg:
            speech_cfg = types.SpeechConfig(voice_config=voice_cfg)

        return types.LiveConnectConfig(
            response_modalities=['AUDIO'],
            speech_config=speech_cfg,
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=config.get_system_instruction(self.active_mode, config.language),
            tools=get_jarvis_tools()
        )

    def is_healthy(self) -> bool:
        """Checks if the underlying websocket connection is active and open."""
        if not self._connected or self.session is None:
            return False
        ws = getattr(self.session, '_ws', None)
        if ws is None:
            return False
        state = getattr(ws, 'state', None)
        # state == 1 is State.OPEN
        return state == 1 or str(state) == 'State.OPEN'

    async def ping(self):
        """Sends a websocket ping to keep the connection alive."""
        if self.is_healthy():
            try:
                ws = self.session._ws
                waiter = await ws.ping()
                await asyncio.wait_for(waiter, timeout=3.0)
                self._last_activity_time = time.time()
            except Exception:
                # If ping fails, mark disconnected so it can reconnect
                self._connected = False

    async def ensure_active_session(self):
        """Proactively checks and warms the Gemini Live session so it never stumbles or stalls."""
        async with self._lock:
            if not self.is_healthy() or getattr(self, "_needs_reconnect", False):
                print("🔄 [Gemini Live] Refreshing session with updated configuration...", flush=True)
                self._needs_reconnect = False
                await self._disconnect_unlocked()
                try:
                    await self._connect_unlocked()
                except Exception as e:
                    print(f"❌ [WARN] Connect failed: {e}", flush=True)
                    self._connected = False
                    self.session = None
                    self._needs_reconnect = True
                return

    async def _connect_unlocked(self):
        connect_config = self._create_config()
        self._session_context = self.client.aio.live.connect(
            model=config.model,
            config=connect_config
        )
        self.session = await self._session_context.__aenter__()
        self._connected = True
        self._needs_reconnect = False
        self._last_activity_time = time.time()

    async def connect(self):
        async with self._lock:
            if self.is_healthy() and not getattr(self, "_needs_reconnect", False):
                return
            self._needs_reconnect = False
            await self._disconnect_unlocked()
            try:
                await self._connect_unlocked()
            except Exception as e:
                self._connected = False
                self.session = None
                raise e

    async def _disconnect_unlocked(self):
        self._connected = False
        if self._session_context and self.session:
            try:
                await self._session_context.__aexit__(None, None, None)
            except Exception:
                pass
        self.session = None
        self._session_context = None

    async def disconnect(self):
        async with self._lock:
            await self._disconnect_unlocked()

    def set_mode(self, new_mode: str):
        if self.active_mode != new_mode:
            self.active_mode = new_mode
            self._needs_reconnect = True

    def set_language(self, new_lang: str):
        if config.language != new_lang:
            config.language = new_lang
            self._needs_reconnect = True

    def set_voice(self, new_voice: str):
        if new_voice in ["Aoede", "Charon"]:
            config.voice_name = new_voice
            config.save_persisted_settings()
            self._needs_reconnect = True

    def set_accent(self, new_accent: str):
        # Deprecated: Accent feature removed in favor of natural native pronunciation
        pass

    def set_respectful(self, enabled: bool):
        config.respectful_address = bool(enabled)
        config.save_persisted_settings()
        self._needs_reconnect = True

    async def _execute_turn(
        self,
        content: types.Content,
        on_audio_chunk: Callable[[bytes], None],
        on_transcript_chunk: Callable[[str], None],
        on_tool_call: Optional[Callable[[str, dict], None]] = None,
        retry_count: int = 0
    ) -> float:
        # Ensure session is healthy and warmed before sending
        await self.ensure_active_session()
        if not self.is_healthy() or self.session is None:
            await self.connect()

        send_time = time.time()
        first_audio_time = None
        has_tool_call = False
        turn_completed = False

        async def _receive_loop():
            nonlocal first_audio_time, has_tool_call, turn_completed
            async for resp in self.session.receive():
                self._last_activity_time = time.time()

                # 1. Handle Tool Calls
                if resp.tool_call and resp.tool_call.function_calls:
                    has_tool_call = True
                    print(f"🔧 [Gemini Live] Received {len(resp.tool_call.function_calls)} tool call(s)", flush=True)
                    for fc in resp.tool_call.function_calls:
                        if on_tool_call:
                            on_tool_call(fc.name, fc.args or {})

                    async def _run_single_tool(fc):
                        print(f"⚙️ [Executing Tool] {fc.name}({fc.args or {}})", flush=True)
                        tool_result = await execute_tool_call(fc.name, fc.args or {})
                        print(f"✅ [Tool Result] {fc.name} -> {tool_result}", flush=True)
                        if self.on_tool_executed:
                            self.on_tool_executed(fc.name, fc.args or {}, tool_result)
                        return types.FunctionResponse(
                            name=fc.name,
                            id=fc.id,
                            response=tool_result
                        )

                    function_responses = await asyncio.gather(*[_run_single_tool(fc) for fc in resp.tool_call.function_calls])

                    is_dismissal = any(fc.name in ["dismiss_assistant", "dismiss", "hide_assistant", "disappear", "close_assistant"] for fc in resp.tool_call.function_calls)
                    if is_dismissal:
                        print("💨 [Gemini Client] Dismissal tool executed. Concluding turn immediately.", flush=True)
                        turn_completed = True
                        break

                    # Send tool results back to Gemini Live
                    if function_responses and self.session is not None:
                        try:
                            await self.session.send_tool_response(function_responses=list(function_responses))
                            self._last_activity_time = time.time()
                        except Exception as te:
                            print(f"❌ [Gemini Live] Failed to send tool response: {te}", flush=True)

                # 2. Handle Server Content (Audio + Transcription)
                if resp.server_content:
                    sc = resp.server_content

                    if sc.output_transcription and sc.output_transcription.text:
                        on_transcript_chunk(sc.output_transcription.text)

                    if sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                if first_audio_time is None:
                                    first_audio_time = time.time()
                                on_audio_chunk(part.inline_data.data)

                    if sc.turn_complete:
                        turn_completed = True
                        break

        try:
            await self.session.send_client_content(turns=content, turn_complete=True)
            self._last_activity_time = time.time()

            # Prevent hanging: max 50.0s wait for Gemini's response and tool execution
            await asyncio.wait_for(_receive_loop(), timeout=50.0)

        except asyncio.CancelledError:
            print("🛑 [Gemini Client] Turn cancelled by caller. Recycling session in background...", flush=True)
            self._connected = False
            await self._disconnect_unlocked()
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.connect())
            except Exception:
                pass
            raise

        except (asyncio.TimeoutError, Exception) as e:
            print(f"⚠️ [Gemini Live] Turn error/timeout ({type(e).__name__}): {e}. Retrying with fresh session...", flush=True)
            self._connected = False
            self._needs_reconnect = True
            await self._disconnect_unlocked()
            if retry_count == 0:
                await self.connect()
                return await self._execute_turn(
                    content=content,
                    on_audio_chunk=on_audio_chunk,
                    on_transcript_chunk=on_transcript_chunk,
                    on_tool_call=on_tool_call,
                    retry_count=1
                )
            raise e

        latency = (first_audio_time - send_time) if first_audio_time else (time.time() - send_time)

        # Automatic Recovery: If session returned empty response (0 audio chunks without tool or completion), retry once!
        if first_audio_time is None and not has_tool_call and not turn_completed and retry_count == 0:
            print("⚠️ [Gemini Live] Session yielded 0 audio chunks without completion. Auto-reconnecting and retrying turn...", flush=True)
            self._connected = False
            self._needs_reconnect = True
            await self._disconnect_unlocked()
            await self.connect()
            return await self._execute_turn(
                content=content,
                on_audio_chunk=on_audio_chunk,
                on_transcript_chunk=on_transcript_chunk,
                on_tool_call=on_tool_call,
                retry_count=1
            )

        return latency

    async def send_audio_turn(
        self,
        pcm_bytes: bytes,
        on_audio_chunk: Callable[[bytes], None],
        on_transcript_chunk: Callable[[str], None],
        on_tool_call: Optional[Callable[[str, dict], None]] = None
    ) -> float:
        content = types.Content(
            role='user',
            parts=[
                types.Part(
                    inline_data=types.Blob(
                        data=pcm_bytes,
                        mime_type=f'audio/pcm;rate={config.sample_rate_in}'
                    )
                )
            ]
        )
        return await self._execute_turn(content, on_audio_chunk, on_transcript_chunk, on_tool_call)

    async def send_text_turn(
        self,
        text_prompt: str,
        on_audio_chunk: Callable[[bytes], None],
        on_transcript_chunk: Callable[[str], None],
        on_tool_call: Optional[Callable[[str, dict], None]] = None
    ) -> float:
        content = types.Content(
            role='user',
            parts=[types.Part.from_text(text=text_prompt)]
        )
        return await self._execute_turn(content, on_audio_chunk, on_transcript_chunk, on_tool_call)
