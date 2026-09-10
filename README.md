# 🦢 SWAN OS — Executive Personal AI Operating Assistant for macOS

Swan is an ultra-refined, discreet, and devoted personal AI operating assistant for macOS powered by **Gemini 3.1 Flash Live Preview** (`gemini-3.1-flash-live-preview`). It provides instantaneous speech recognition, a floating Apple-style **Liquid Glass HUD**, native **"Swan"** wake word detection, and deep macOS automation—from file and folder management to instant Spotify music playback.

---

## 🌟 Key Capabilities & Features

### 1. ⚡ Instant Wake Word & Continuous Commands
- **Wake Word Detection:** Responds immediately to **"Swan"** or **"Hey Swan"** in **< 20ms**.
- **Continuous Command Mode:** Speak your request in one breath (*"Swan, open Safari"* or *"Swan, play Bohemian Rhapsody"*). Swan seamlessly captures the command without requiring you to wait for an acknowledgment prompt.
- **Push-to-Talk Hotkey:** Hold **`Option + Shift`** anywhere on macOS to speak directly.

### 2. 💧 Liquid Glass HUD (Dynamic Island for macOS)
- A floating, borderless, click-through pill located at the top center of the screen (`NSWindowCollectionBehaviorCanJoinAllSpaces`).
- **Smooth State Progression:**
  - `Wake` ➔ Poised glow with studio acknowledgment (*"Yes, sir."*, *"Listening, sir."*, *"Buyuring, Janob."*, *"Dinliyorum, efendim."*).
  - `Listening` ➔ Radiant emerald pill with breathing voice wave animation.
  - `Thinking` ➔ Amber pulsing glow while Gemini Live processes.
  - `Action` ➔ Displays live system action labels (*"Opening Safari..."*, *"Playing 'Starboy' on Spotify..."*, *"Moving to Trash..."*).
  - `Speaking` ➔ Violet glow while Swan speaks her response.

### 3. 🌍 Multilingual Intelligence & Dynamic Language Switching
Swan automatically detects the language spoken by the user on every turn and responds in that exact language with flawless native pronunciation:
- **English:** British Butler (Received Pronunciation) or General American.
- **Uzbek (O'zbekcha):** Pure literary Uzbek addressing the user as *"Janob"*.
- **Turkish (Türkçe):** Fluent standard Turkish addressing the user as *"efendim"*.

### 4. 🎙️ Voice Models & Character Personalities
Choose from 5 native Gemini Live neural voice models:
- **Kore (Calm / British):** Distinguished, calm, executive assistant.
- **Charon (Male Butler / Jarvis):** Deep, authoritative, confident butler.
- **Aoede (Female / American):** Poised, crisp, natural.
- **Fenrir (Male / Resonant):** Deep and grounding.
- **Puck (Male / Upbeat):** Energetic and lively.

### 5. 🎩 Respectful Address Toggle
- **Enabled (Default):** Addresses the user with titles (*"sir"*, *"Janob"*, *"efendim"*).
- **Disabled:** Title-free, direct, and modern (*"Opening Safari."*, *"Listening."*, *"Safari ochilmoqda."*, *"Dinliyorum."*).

### 6. 🎵 Native Spotify & Music Control
Sub-second control over Spotify using native macOS IPC (`spotify_cli`) and AppleScript:
- **Play / Resume:** *"Play music on Spotify"*, *"Spotify-da musiqa qo'y"*, *"Spotify'da müzik çal"*.
- **Search & Play:** *"Play Bohemian Rhapsody"*, *"Play The Weeknd"*, *"Play Starboy"*, *"Play Adele"*.
- **Curated Moods:** *"Play lofi beats"*, *"Play workout music"*, *"Play jazz"*, *"Play my liked songs"*.
- **Playback Controls:** *"Pause music"*, *"Resume"*, *"Next track"*, *"Previous song"*, *"What song is this?"*.

### 7. 📁 Files & Folders Management
- **Open Folders:** *"Open Downloads"*, *"Open Desktop"*, *"Open Projects"*.
- **Create Folders:** *"Create folder Invoices on Desktop"*.
- **Rename Items:** *"Rename draft to final.pdf in Downloads"*.
- **Batch Move:** *"Move all screenshots to Pictures"*, *"Move invoice.pdf from Downloads to Documents"*.
- **Safe Trash:** *"Delete folder Temp on Desktop"*, *"Move test.txt to Trash"* (moves to `~/.Trash` with full `⌘Z` undo support).

### 8. ⚙️ Apple-Style Settings GUI (`⌘,`)
Access the preferences window from the menu bar (`🦢` ➔ **Preferences...**) or by pressing **`⌘,`**:
- **Assistant Persona:** Switch between Command Mode (system actions) and Chat Mode (conversational partner).
- **Language Selection:** Default language (Uzbek, Turkish, English).
- **Wake Word Sensitivity:** Low (filters background YouTube/TV noise), Medium (balanced), High.
- **Voice Model & Accent:** Select model and British/American accent.
- **Respectful Address:** Toggle honorific titles on/off.

---

## 🏛️ System Architecture & Codebase Map

| File | Purpose |
| :--- | :--- |
| **`app.py`** | Main application coordinator, event loop, VAD listener, wake word handling, and multi-turn conversation flow. |
| **`audio_manager.py`** | PyAudio / SoundDevice audio I/O with 2-channel stereo MacBook speaker adaptation and low-latency circular buffer. |
| **`audio_prompts.py`** | Local studio-recorded 24kHz audio acknowledgment prompts categorized by voice model, language, and respect preference. |
| **`wake_word_detector.py`** | Ultra-responsive offline Vosk wake word recognizer (< 20ms) with rolling RMS memory and phonetic distractor filtering. |
| **`tools.py`** | Native macOS tools: Spotify control (`spotify_cli`), Finder file management, app launch/quit, Apple Notes, Reminders, system controls. |
| **`gemini_client.py`** | Bidirectional real-time Gemini Live WebSocket client (`LiveConnectConfig`) with session warming and keep-alive. |
| **`config.py`** | System instructions, prompts, accent steering, and persistent user configuration loader (`swan_settings.json`). |
| **`hud_window.py`** | Floating macOS WKWebView transparent HUD window controller. |
| **`hud_template.html`** | HTML/CSS/JS frontend for the liquid glass dynamic pill HUD with smooth CSS animations. |
| **`settings_window.py`** | macOS WKWebView controller for the Apple-style Settings and Preferences window. |
| **`settings_template.html`**| HTML/CSS/JS frontend for the frosted glass Settings window. |
| **`menu_bar.py`** | Status bar menu (`🦢`) with quick toggles, mode switching, and settings access. |
| **`hotkey_manager.py`** | Global hotkey listener for `Option + Shift` push-to-talk. |
| **`swan_settings.json`** | Persistent JSON store for active user settings. |

---

## 🚀 Running Swan

### Start Assistant
```bash
cd /Users/ahmetyadgarov/gemini-live-assistant
./.venv/bin/python -u app.py
```

### Stop Assistant
```bash
pkill -f "app.py"
rm -f /tmp/swan_assistant.lock
```

---

## 🔒 Configuration (`swan_settings.json`)
```json
{
  "language": "en",
  "wake_sensitivity": "medium",
  "mode": "command",
  "voice_name": "Kore",
  "accent": "british",
  "respectful_address": true
}
```
