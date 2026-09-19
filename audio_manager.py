import queue
import threading
import time
from collections import deque
import numpy as np
import sounddevice as sd
from config import config

def generate_chime(freqs, duration_per_freq=0.035, sr=24000, volume=0.12):
    chunks = []
    for f in freqs:
        t = np.linspace(0, duration_per_freq, int(sr * duration_per_freq), endpoint=False)
        envelope = np.exp(-t * 28)
        wave = volume * np.sin(2 * np.pi * f * t) * envelope
        chunks.append(wave)
    waveform = np.concatenate(chunks)
    return (waveform * 32767).astype(np.int16)

class AudioManager:
    def __init__(self):
        self.sr_in = config.sample_rate_in
        self.sr_out = config.sample_rate_out
        self.channels = config.channels

        # Native output channel mapping (stereo for Mac speakers to prevent AUHAL -50)
        try:
            dev_info = sd.query_devices(kind='output')
            self.channels_out = min(2, max(1, dev_info.get('max_output_channels', 2)))
        except Exception:
            self.channels_out = 2

        # Recording state
        self._recording = False
        self._record_buffer = []
        self._preroll_max = 40     # ~2.56s of audio history for seamless command capture
        self._preroll_buffer = deque(maxlen=self._preroll_max)  # Ring buffer of recent mic chunks
        self._record_lock = threading.Lock()
        self.current_rms = 0.0

        # Playback queue and worker
        self._play_queue = queue.Queue()
        self._running = True
        self._is_playing = False
        self._interrupted_playback = False

        # Synthesize chimes (at output sample rate: 24kHz)
        self.start_chime = generate_chime([587.33, 880.0], volume=0.10)   # D5 -> A5
        self.stop_chime = generate_chime([783.99, 523.25], volume=0.08)    # G5 -> C5
        self.error_chime = generate_chime([220.0, 180.0], duration_per_freq=0.07, volume=0.15)

        # Streams & Workers
        self._in_stream = None
        self._out_stream = None
        self._playback_thread = None
        self._wake_thread = None
        self._wake_queue = queue.Queue(maxsize=150)
        self.wake_word_callback = None
        self.interruption_callback = None
        self.speaker_rms = 0.0

        self._start()

    def set_wake_word_callback(self, cb):
        self.wake_word_callback = cb

    def set_interruption_callback(self, cb):
        self.interruption_callback = cb

    def _start(self):
        try:
            # Input Stream (16kHz 16-bit mono)
            self._in_stream = sd.InputStream(
                samplerate=self.sr_in,
                channels=self.channels,
                dtype='int16',
                blocksize=1024,
                callback=self._mic_callback
            )
            self._in_stream.start()
        except Exception as e:
            print(f"⚠️ [AudioManager] Failed to open microphone input stream: {e}", flush=True)

        try:
            # Output Stream (24kHz 16-bit native stereo/mono matching hardware)
            self._out_stream = sd.OutputStream(
                samplerate=self.sr_out,
                channels=self.channels_out,
                dtype='int16',
                blocksize=1024
            )
            self._out_stream.start()
        except Exception as e:
            print(f"⚠️ [AudioManager] Failed to open speaker output stream: {e}", flush=True)

        self._playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self._playback_thread.start()

        self._wake_thread = threading.Thread(target=self._wake_worker, daemon=True)
        self._wake_thread.start()

    def _mic_callback(self, indata, frames, time_info, status):
        chunk = indata.copy()
        arr = chunk.astype(np.float32)
        rms = float(np.sqrt(np.mean(arr ** 2)) / 32768.0)
        self.current_rms = rms

        with self._record_lock:
            self._preroll_buffer.append(chunk)
            if self._recording:
                self._record_buffer.append(chunk)

        # Enqueue mic chunks for idle wake detection OR playback interruption detection
        if not self._recording:
            if (self.wake_word_callback and not self._is_playing) or (self.interruption_callback and self._is_playing):
                try:
                    self._wake_queue.put_nowait(chunk.tobytes())
                except queue.Full:
                    pass

    def _wake_worker(self):
        while self._running:
            try:
                pcm_bytes = self._wake_queue.get(timeout=0.08)
            except queue.Empty:
                continue

            if self._recording:
                continue

            if self._is_playing and self.interruption_callback:
                try:
                    self.interruption_callback(pcm_bytes, self.current_rms, self.speaker_rms)
                except Exception:
                    pass
            elif not self._is_playing and self.wake_word_callback:
                try:
                    self.wake_word_callback(pcm_bytes)
                except Exception:
                    pass

    def start_recording(self, play_chime: bool = False, include_preroll: bool = False):
        """Called when hotkey is pressed or after wake acknowledgment. Optionally preserves preroll mic history."""
        self.interrupt_playback()
        while not self._wake_queue.empty():
            try:
                self._wake_queue.get_nowait()
            except Exception:
                break
        with self._record_lock:
            if include_preroll and self._preroll_buffer:
                self._record_buffer = list(self._preroll_buffer)
            else:
                self._record_buffer.clear()
            self._preroll_buffer.clear()
            self._recording = True
        if play_chime and config.play_chimes:
            self._play_queue.put(self.start_chime)

    def stop_recording(self, play_chime: bool = False) -> bytes:
        """Called when hotkey is released. Returns complete PCM bytes."""
        with self._record_lock:
            self._recording = False
            if not self._record_buffer:
                return b""
            all_chunks = np.concatenate(self._record_buffer, axis=0)
            self._record_buffer.clear()

        if play_chime and config.play_chimes:
            self._play_queue.put(self.stop_chime)

        return all_chunks.tobytes()

    def is_recording(self) -> bool:
        return self._recording

    def has_speech(self, pcm_bytes: bytes, energy_threshold: float = 0.012, min_speech_duration: float = 0.15) -> bool:
        """
        Determines whether the audio recording contains real speech or only ambient silence/background noise.
        """
        if not pcm_bytes or len(pcm_bytes) < self.sr_in * 2 * 0.2: # < 0.2 seconds
            return False

        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        
        # 50ms frame analysis
        frame_size = int(self.sr_in * 0.05)
        if len(samples) < frame_size:
            return False

        num_frames = len(samples) // frame_size
        speech_frame_count = 0
        required_speech_frames = max(3, int(min_speech_duration / 0.05))

        for i in range(num_frames):
            frame = samples[i * frame_size : (i + 1) * frame_size]
            rms = np.sqrt(np.mean(frame ** 2))
            if rms > energy_threshold:
                speech_frame_count += 1
                if speech_frame_count >= required_speech_frames:
                    return True

        return False

    def has_preroll(self) -> bool:
        """Returns True if recent mic preroll audio buffer contains frames."""
        with self._record_lock:
            return len(self._preroll_buffer) > 0

    def play_audio_chunk(self, pcm_bytes: bytes):
        """Enqueue PCM bytes (24kHz int16 mono) for gapless playback."""
        if not pcm_bytes or not self._running:
            return
        self._interrupted_playback = False
        audio_np = np.frombuffer(pcm_bytes, dtype=np.int16)
        self._play_queue.put(audio_np)

    def interrupt_playback(self):
        """Immediately stops queued playback (barge-in)."""
        self._interrupted_playback = True
        while not self._play_queue.empty():
            try:
                self._play_queue.get_nowait()
                self._play_queue.task_done()
            except Exception:
                break
        self._is_playing = False
        self.speaker_rms = 0.0

    def is_playing(self) -> bool:
        return self._is_playing or not self._play_queue.empty()

    def play_prompt(self, pcm_np: np.ndarray):
        """Immediately plays a short pre-buffered voice prompt."""
        self.interrupt_playback()
        self._interrupted_playback = False
        self._play_queue.put(pcm_np)

    def get_active_rms(self) -> float:
        """Returns the current active audio energy (mic while recording, speaker while playing)."""
        if self._recording:
            return self.current_rms
        if self.is_playing():
            return getattr(self, "speaker_rms", 0.05)
        return 0.02

    def _playback_worker(self):
        while self._running:
            try:
                chunk = self._play_queue.get(timeout=0.05)
            except queue.Empty:
                self._is_playing = False
                self.speaker_rms = 0.0
                continue

            self._is_playing = True
            try:
                # Calculate output RMS for liquid wave HUD
                arr = chunk.astype(np.float32)
                rms = float(np.sqrt(np.mean(arr ** 2)) / 32768.0)
                self.speaker_rms = rms

                if chunk.ndim == 1 and self.channels_out == 2:
                    out_chunk = np.column_stack([chunk, chunk])
                else:
                    out_chunk = chunk

                # Sliced write in 1024-sample blocks (~42ms) so interruptions abort immediately
                step = 1024
                for i in range(0, len(out_chunk), step):
                    if not self._running or self._interrupted_playback:
                        break
                    sub_chunk = out_chunk[i : i + step]
                    if self._out_stream and not self._out_stream.closed:
                        try:
                            self._out_stream.write(sub_chunk)
                        except Exception:
                            try:
                                self._out_stream.close()
                                self._out_stream = sd.OutputStream(
                                    samplerate=self.sr_out,
                                    channels=self.channels_out,
                                    dtype='int16',
                                    blocksize=1024
                                )
                                self._out_stream.start()
                                self._out_stream.write(sub_chunk)
                            except Exception:
                                pass
            except Exception:
                pass
            finally:
                self._play_queue.task_done()

    def close(self):
        self._running = False
        self._recording = False
        self.interrupt_playback()
        try:
            if self._in_stream:
                self._in_stream.stop()
                self._in_stream.close()
        except Exception:
            pass
        try:
            if self._out_stream:
                self._out_stream.stop()
                self._out_stream.close()
        except Exception:
            pass
