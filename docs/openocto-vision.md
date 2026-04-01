# OpenOcto — Vision & Goals

## Manifesto

The era of smart speakers is coming to an end. Alisa, Alexa, Google Assistant — they all follow the same pattern: your voice flies off to a corporate cloud, goes through censorship and restrictions, and you get a response that someone decided to allow you. You don't control your data. You can't extend the functionality. You're locked into a single vendor's ecosystem.

**OpenOcto** is the next step. An open constructor for personal AI assistants. You choose the personality, voice, brain, and appearance of your assistant — and it runs on your hardware, fully under your control.

OpenClaw showed the world that a personal AI agent on a Mac Mini is a reality. OpenOcto goes further: **create your own agent with personality, voice, and soul**.

**Key principles:**
- Fully local voice processing — no audio data leaves the device
- Cross-platform: macOS, Windows, Linux
- Persona system — choose or create your assistant's character
- AI provider agnostic — Claude, OpenAI, Ollama, Gonka
- Open-source (BSL 1.1 License)
- OpenClaw as an optional backend for agentic tasks

**Mascot:** 🐙 Octopus — nine brains, eight tentacles, infinite possibilities.

**Author:** [Rocket Dev](https://rocketdev.io)

---

## Why an Octopus

The octopus is not a random choice. It's the most intelligent invertebrate on the planet:

- **Nine brains** — one central and a mini-brain in each tentacle. Each tentacle can act autonomously. It's literally a distributed system — a metaphor for multi-agent architecture.
- **Eight tentacles = multitasking** — simultaneously searching for a movie, playing music, checking the weather, and controlling lights.
- **Adaptation** — an octopus instantly changes color and texture. The assistant adapts to the user's context, language, and mood.
- **Tools** — octopuses use tools, open jars, solve mazes. A symbol of practical intelligence.
- **Non-aggressive** — associated with curiosity and cleverness, not threat. The right tone for a home assistant.

In IT culture, sea creatures are part of the DNA: O'Reilly with their animal engravings, GitHub with Octocat, OpenClaw with the lobster. OpenOcto with the octopus fits naturally into this tradition.

---

## Who This Project Is For

**Home user** who wants to:
- Control a media center by voice — search and play movies, music, photos
- Get answers to questions without restrictions and censorship
- Control a smart home with a single voice
- Not depend on subscriptions, servers, and corporate decisions
- Choose the assistant's character that they like

**Tech enthusiast** who wants to:
- Build and customize an assistant for themselves
- Write their own skills, integrations, and personas
- Experiment with AI models locally
- Participate in the open-source community

**User in Russia and CIS countries**, for whom:
- Cloud media services are limited or unavailable
- Local storage and file management is a necessity, not a choice
- Yandex Alisa is too limited and tied to the Yandex ecosystem
- Russian language support at a level comparable to commercial solutions matters

**Small business** (VR arcades, anti-cafes, coworking spaces) who wants:
- Voice-controlled multimedia in a venue
- Automation of routine tasks without expensive enterprise solutions
- Control over customer data without sharing with third parties

---

## Persona System — The Key Feature

### Concept

A persona is not just a name. It's a package: **character + voice + system prompt + avatar + skill set**. The user chooses or creates a persona during initial setup through a visual wizard.

It's like creating a character in an RPG: you choose a class, appearance, attributes — and get a unique assistant that behaves exactly the way you need.

### Built-in Personas (Starter Set)

| Persona | Wake word | Character | Voice | Visual style | Target audience |
|---------|-----------|-----------|-------|--------------|-----------------|
| 🔥 **Hestia** | "Hestia" | Warm homekeeper. Caring, calm, patient. Goddess of the hearth in Greek mythology — the one who welcomes people in their homes, guards and watches over them | Soft female | Octopus in an apron by the fireplace, warm tones | Family, home, everyday tasks |
| 🧠 **Metis** | "Metis" | Smart advisor. Concise, precise, strategic. Goddess of wise counsel in mythology — an advisor who always knows what to do | Confident female | Elegant octopus with glasses, blue tones | Planning, analytics, business |
| 📚 **Nestor** | "Nestor" | Wise mentor. Patient, thorough, educated. The sage from the "Iliad" + Russian chronicler Nestor | Calm male | Professor octopus with a book, warm brown | Education, children, explanations |
| 🫖 **Sofia** | "Sofia" | Psychologist-companion. Empathetic, gentle, supportive. "Wisdom" in Greek | Warm female | Octopus with a cup of tea, pastel tones | Reflection, planning, support |
| 👁️ **Argus** | "Argus" | Guard and monitoring. Serious, attentive, laconic. The mythological all-seeing guardian with 100 eyes | Low male | Guardian octopus, dark tones | Security, monitoring, smart home |
| 🐙 **Octo** | "Octo" | Default, neutral. Friendly, universal. The project's base mascot | Neutral | Standard mascot, bright colors | Quick start, all-purpose |

### Persona Anatomy (Technical)

Each persona is a set of files in a directory:

```
personas/
├── hestia/
│   ├── persona.yaml        # Configuration
│   ├── system_prompt.md     # System prompt for AI
│   ├── avatar.png           # Avatar for UI
│   ├── avatar_promo.png     # Promo image (high resolution)
│   └── sounds/              # Custom activation sounds
│       ├── activate.wav
│       └── deactivate.wav
├── metis/
│   ├── persona.yaml
│   ├── system_prompt.md
│   └── ...
└── custom/                  # User-created personas
```

**persona.yaml:**
```yaml
name: "Hestia"
display_name: "Hestia"
description: "Warm homekeeper. Caring, calm, patient."
origin: "Goddess of the hearth in Greek mythology"

wakeword: "hey_hestia"
wakeword_display: "Hestia"

voice:
  engine: "piper"
  model: "en_US-amy-medium"
  length_scale: 1.05        # Slightly slower — calmer

personality:
  tone: "warm"               # warm, professional, playful, serious
  verbosity: "balanced"      # brief, balanced, detailed
  humor: "gentle"            # none, gentle, witty, sarcastic
  formality: "informal"      # formal, informal, casual

skills:
  - media_control
  - smart_home
  - reminders
  - cooking_assistant

tags: ["home", "family", "female"]
```

### Assistant Creation Wizard

On first launch, OpenOcto starts a local web interface and guides the user through a visual wizard:

```
🐙 Welcome to OpenOcto!
   Let's create your personal AI assistant.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1 of 5: Choose a Persona

   ┌────────────┐  ┌────────────┐  ┌────────────┐
   │ 🔥         │  │ 🧠         │  │ 📚         │
   │ [avatar]   │  │ [avatar]   │  │ [avatar]   │
   │            │  │            │  │            │
   │  Hestia    │  │  Metis     │  │  Nestor    │
   │  Home-     │  │  Advisor   │  │  Mentor    │
   │  keeper    │  │            │  │            │
   └────────────┘  └────────────┘  └────────────┘
   ┌────────────┐  ┌────────────┐  ┌────────────┐
   │ 🫖         │  │ 👁️         │  │ ✨         │
   │ [avatar]   │  │ [avatar]   │  │            │
   │            │  │            │  │   +        │
   │  Sofia     │  │  Argus     │  │ Create     │
   │  Companion │  │  Guardian  │  │ your own   │
   └────────────┘  └────────────┘  └────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 2 of 5: Configure Voice

   Language:  ◉ English  ○ Russian  ○ Auto

   Voice: ◉ Amy (warm female)
          ○ Ryan (calm male)
          ○ Jenny (energetic female)
          [▶ Listen]

   Speed: [====●======] Normal

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 3 of 5: Choose AI Engine

   ◉ Claude (Anthropic)
     Best response quality. API key required.
     [Enter API key: ________________]

   ○ Ollama (local)
     Free, fully offline. Requires 16+ GB RAM.
     Models: Llama 3, Mistral, Qwen

   ○ OpenAI (GPT-4o)
     API key required.

   ○ Gonka (decentralized network)
     Access to open-source models via blockchain.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 4 of 5: Wake Word

   Your assistant will respond to:
   [  Hestia  ]

   "Hey, Hestia, play some music" ✓
   "Hestia, what's the weather?" ✓

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 5 of 5: Connections (optional)

   □ OpenClaw Gateway (agentic tasks, browser, files)
     URL: [ws://127.0.0.1:18789]

   □ Home Assistant (smart home)
     URL: [http://homeassistant.local:8123]

   □ Telegram (remote control)
     Bot token: [________________]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   [✨ Create My Assistant]
```

The wizard is implemented as a React app on `localhost:3000`, launched on the first run of `openocto setup`. All settings are saved to `~/.openocto/config.yaml`.

---

## Primary Use Cases

### Media Center with Voice Control

The main scenario — turning a Mac Mini (or another PC) into a home media hub with AI control.

**Searching and watching content:**
- "Hestia, find interesting new sci-fi releases on torrents from the last month"
- The assistant searches, filters already watched content, suggests a list with descriptions and ratings
- "Download the second option" → starts the download
- "Play the downloaded movie" → opens in VLC/mpv on the connected TV

**Music:**
- "Play something calm for the evening"
- "Start the workout playlist on Spotify"
- "What's playing now?" / "Next track" / "Turn it down"
- Works with local library, Spotify, and streaming services

**Photos and video:**
- "Find photos from the beach last summer"
- "Show videos from Masha's birthday"
- "Make a compilation of the best photos this year and start a slideshow"

### Information Assistant

**Everyday questions:**
- "What day of the week is April 1st?"
- "Convert 150 euros to dollars"
- "Set a timer for 15 minutes"

**Planning:**
- "Find ticket prices for three people to Istanbul, direct or with one convenient layover no longer than 3 hours. With and without checked bags. What airline and aircraft type?"
- "What to do this weekend in the city with a group of four, mid-range budget?"
- "Where to find apartment rentals in Miami? What's the cost of a one-bedroom?"

**Education:**
- "Nestor, explain to a 6-year-old how an internal combustion engine works"
- "Explain in simple terms what blockchain is"

### Smart Home Control

**Home Assistant integration:**
- "Turn off the lights in the bedroom"
- "What's the temperature in the kids' room?"
- "Close the curtains in the living room"

**Scenes:**
- "I'm leaving" → turns off lights, sets temperature to eco mode, enables security sensors
- "Good morning" → turns on lights, reads forecast and schedule
- "Movie night" → dims lights, turns on TV, suggests movies

### Productivity and Everyday Tasks

- "Remind me tomorrow at 9 AM to call the clinic"
- "What are the plans for tomorrow?"
- "Send a message to Masha on Telegram: I'll be there in 20 minutes"

---

## Advanced Features

### Contextual Conversation Memory

The assistant remembers context within a session and across sessions:

- "Find flights to Istanbul" → gives results
- An hour later: "What if I fly on Friday?" → remembers the topic is Istanbul
- The next day: "Book that Turkish Airlines flight" → remembers the option

Implemented via local storage (SQLite) and passing relevant context in the prompt.

### Multi-room Audio

Multiple microphones and speakers in different rooms, connected to a single Mac Mini. The assistant identifies which room the command came from and responds through the same speaker.

### Voice Recognition (Speaker ID)

Distinguishing family members by voice. Different people — different briefings, different preferences, different access levels. Children cannot issue certain commands.

### Proactive Notifications

The assistant initiates communication on its own:
- "You have a meeting with Peter in 30 minutes"
- "Movie download complete. Want to watch?"
- "The exchange rate went above a threshold"
- "Today is Masha's birthday"

### Voice Routines

User-defined scenarios triggered by voice or on schedule:
- **Morning briefing:** weather → schedule → reminders → news
- **Evening report:** download summaries → new emails → tomorrow's tasks
- **Cooking assistant:** step-by-step recipe dictated one step at a time

### Radio / Podcast Mode

- "Tell me today's tech news" → searches, summarizes, narrates
- "Read me the article from Hacker News about Rust"
- Continuous audio stream: news → weather → interesting facts

### Desktop Voice Control

- "Open the terminal"
- "Take a screenshot and send it to Telegram"
- "Find the file with the March report"

### Offline Mode with Local LLM

Full autonomy: Ollama + Llama 3 / Mistral / Qwen. Ideal for countryside homes and places with unstable internet. Graceful degradation: no internet — local model; online — cloud model.

### Multilingual with Auto-switching

Speak in English — responds in English. Switch to Russian — responds in Russian. Automatic detection via Whisper.

### Kids Mode

Age-appropriate content filtering, usage time limits, educational quizzes, bedtime stories, lesson timers.

### Sound Monitoring

Detection of breaking glass, alarms, smoke detector sounds. Phone notification (via YAMNet).

### Learning Through Usage

Remembers frequent commands, learns preferences, adapts VAD threshold for the specific microphone, trains wake word model for the owner's voice.

---

## Ecosystem Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenOcto Ecosystem                        │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              OpenOcto Core (Python)                   │   │
│  │  ┌─────────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌───────────┐ │   │
│  │  │WakeWord │ │ VAD │ │ STT │ │ TTS │ │  Persona  │ │   │
│  │  │OpenWake │ │Sile-│ │Whis-│ │Piper│ │  Manager  │ │   │
│  │  │Word     │ │ro   │ │per  │ │     │ │           │ │   │
│  │  └─────────┘ └─────┘ └─────┘ └─────┘ └───────────┘ │   │
│  │  ┌─────────────────┐  ┌──────────────────────────┐  │   │
│  │  │  State Machine   │  │  Setup Wizard (React)    │  │   │
│  │  │                  │  │  localhost:3000           │  │   │
│  │  └─────────────────┘  └──────────────────────────┘  │   │
│  └──────────────────────────┬───────────────────────────┘   │
│                              │ WebSocket / REST              │
│  ┌───────────────────────────┼──────────────────────────┐   │
│  │         Backends (user's choice)                      │   │
│  │                           │                           │   │
│  │  ┌───────────┐  ┌────────┴────────┐  ┌────────────┐ │   │
│  │  │ OpenClaw  │  │  Direct AI API  │  │   Ollama   │ │   │
│  │  │ Gateway   │  │  Claude/OpenAI  │  │   Local    │ │   │
│  │  │ (agents,  │  │  Gonka          │  │   LLM      │ │   │
│  │  │  browser, │  │                 │  │            │ │   │
│  │  │  files)   │  │                 │  │            │ │   │
│  │  └───────────┘  └─────────────────┘  └────────────┘ │   │
│  └──────────────────────────────────────────────────────┘   │
│                              │                               │
│  ┌───────────────────────────┼──────────────────────────┐   │
│  │         Integrations                                  │   │
│  │                           │                           │   │
│  │  ┌────────────┐  ┌───────┴───────┐  ┌─────────────┐ │   │
│  │  │ Home       │  │  Telegram /   │  │ OpenOcto    │ │   │
│  │  │ Assistant  │  │  WhatsApp     │  │ Mobile App  │ │   │
│  │  │            │  │  (text cmds)  │  │ (iOS/Andr.) │ │   │
│  │  └────────────┘  └───────────────┘  └─────────────┘ │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### OpenClaw as a Backend

OpenOcto doesn't replace OpenClaw, it **builds on top of it**:

- **OpenOcto** = voice interface + personas + wizard + mobile app
- **OpenClaw** = agentic core (browser, files, shell, messengers, skills)

OpenClaw is an optional backend. The user can:
1. Use OpenOcto standalone (voice → AI API → voice) — for simple questions
2. Connect OpenClaw Gateway — for agentic tasks (torrents, file management, browser)
3. Connect Home Assistant — for smart home control

This allows starting simple and scaling as needed.

---

## OpenOcto Mobile App

### Concept

The mobile app is a **remote control and window into the assistant's world**. Not a replacement for voice, but a complement: when you're away from home, when it's inconvenient to speak aloud, when you need a quick status check.

### Key Features

**Remote control:**
- Send text and voice commands to the assistant from anywhere
- Push notifications: "Download complete", "Reminder", "Sensor triggered"
- Quick actions: "Turn on the living room lights" with a single button

**Status dashboard:**
- Current assistant status (online/offline, what it's doing)
- Active downloads and their progress
- Smart home status: temperature, lighting, sensors
- Command and response history

**Persona management:**
- Switch between personas on the fly
- View and edit persona settings
- Download new personas from the marketplace

**Media control:**
- Playback remote (play/pause/skip/volume)
- View playback queue
- Select output device (which room)

### Mobile App Monetization

**Free version:**
- Text commands
- Basic status dashboard
- Push notifications (limited)

**Premium (subscription ~$3-5/mo or one-time purchase):**
- Voice commands from the app
- Full dashboard with widgets
- Unlimited push notifications
- Custom widgets for iOS/Android
- Priority support

### Why This Works Commercially

1. **The server side remains open-source** — the user installs OpenOcto for free, configures it, uses voice at home. The app is an optional convenience.
2. **Alternatives are not prohibited** — enthusiasts can write their own client (a Telegram bot is included out of the box). But the official app from the project creator will be more complete, more convenient, and more trustworthy.
3. **Maintainer advantage** — the name of the lead developer and maintainer = a quality mark. Like Linus Torvalds for Linux — forks exist, but the original is the original.
4. **App Store / Google Play — barrier for clones.** To publish an alternative in the stores, you need to invest time and money. Most enthusiasts will prefer to pay $5 rather than spend weeks developing.

### Technical Implementation

```
OpenOcto Mobile App (React Native)
├── Connection to Mac Mini via Tailscale / WireGuard VPN
│   (secure tunnel, works from any network)
├── REST API on OpenOcto Core (localhost → Tailscale)
├── WebSocket for real-time updates
├── Firebase / OneSignal for push notifications
└── Offline mode: cache of recent statuses
```

---

## Competitive Comparison

| Feature | Yandex Alisa | Google Assistant | Amazon Alexa | OpenClaw | **OpenOcto** |
|---------|:---:|:---:|:---:|:---:|:---:|
| Voice control | ✅ | ✅ | ✅ | partial | ✅ |
| Character personalization | ❌ | ❌ | ❌ | ❌ | ✅ personas |
| Setup wizard | ❌ | ❌ | ❌ | CLI | ✅ visual |
| Mobile app | ✅ | ✅ | ✅ | ❌ | ✅ |
| Runs locally | ❌ | ❌ | ❌ | ✅ | ✅ |
| Data on device | ❌ | ❌ | ❌ | ✅ | ✅ |
| No censorship | ❌ | ❌ | ❌ | ✅ | ✅ |
| Open-source | ❌ | ❌ | ❌ | ✅ | ✅ |
| AI model choice | ❌ | ❌ | ❌ | ✅ | ✅ |
| File management | ❌ | ❌ | ❌ | ✅ | ✅ (via OpenClaw) |
| Smart home | Yandex | Google | Amazon | community | ✅ Home Assistant |
| Offline mode | partial | partial | partial | ✅ | ✅ |

**Key difference from OpenClaw:** OpenClaw is a powerful agent for tech-savvy users (CLI, configs, terminal). OpenOcto is a user-friendly wrapper with voice, wizard, and personas, accessible to regular people. OpenClaw can work as a backend for OpenOcto.

---

## Monetization Model

### Free (open-source core)
- OpenOcto Core with voice control
- All built-in personas
- Setup wizard
- Telegram bot for remote control
- Integration with OpenClaw and Home Assistant
- Community support

### Mobile App (primary revenue)
- Free version with basic functionality
- Premium: voice, widgets, full dashboard, push — $3-5/mo

### Persona Marketplace
- Free community personas
- Premium personas with unique voices and original art
- Sales commission (if community creates paid personas)

### Pre-installed Devices
- Mac Mini / mini-PC with pre-installed OpenOcto
- "Out of the box" for non-technical users
- For VR arcades, anti-cafes, coworking spaces

### Consulting and Customization
- Setup for business use cases through Rocket Dev
- Custom integrations
- Technical support

---

## Why Open-Source

### Trust Through Transparency

A home assistant with constant microphone access is a matter of maximum trust. The user must be able to verify that audio is not recorded or sent to third parties.

### Legal Protection

In the open-source model, the user deploys and operates the system themselves. Data stays on their device. The developer provides a tool, not a service.

### Ecosystem

The community writes personas, skills, and integrations. Localization for different languages. Adaptation for specific scenarios.

---

## Tech Stack (Summary)

| Component | Technology | Why |
|-----------|-----------|-----|
| Core runtime | Python 3.10+ | ML ecosystem, cross-platform |
| Setup wizard & web UI | React (TypeScript) | Beautiful UI, rapid development |
| Mobile app | React Native | Single codebase for iOS and Android |
| AI backbone (opt.) | OpenClaw (Node.js/TS) | Ready-made agentic platform |
| Wake word | OpenWakeWord | Open-source, ready "hey jarvis" model |
| VAD | Silero VAD | 2MB model, high accuracy |
| STT | whisper.cpp | Local, fast, excellent multilingual |
| TTS | Piper / Silero TTS | Fast / high-quality voices |
| AI models | Claude, OpenAI, Ollama, Gonka | Agnostic |
| Smart home | Home Assistant | De facto standard |
| Remote access | Tailscale / WireGuard | Secure access from mobile app |

---

## Roadmap

### Phase 1 — MVP
- [ ] Voice pipeline (wake word → VAD → STT → AI → TTS)
- [ ] Standalone mode (direct API without OpenClaw)
- [ ] Basic configuration via YAML
- [ ] CLI interface
- [ ] One default persona (Octo)

### Phase 2 — Personas and Wizard
- [ ] Persona system (yaml + system prompt + voice config)
- [ ] Setup wizard (React, localhost:3000)
- [ ] 6 built-in personas (Hestia, Metis, Nestor, Sofia, Argus, Octo)
- [ ] Web UI for management and monitoring
- [ ] Integration with OpenClaw Gateway

### Phase 3 — Mobile App
- [ ] React Native app (iOS + Android)
- [ ] Push notifications
- [ ] Voice commands from the app
- [ ] Status dashboard and media control
- [ ] Tailscale integration for remote access

### Phase 4 — Ecosystem
- [ ] Persona marketplace
- [ ] Community-created personas and skills
- [ ] Speaker ID (voice recognition)
- [ ] Multi-room audio
- [ ] Home Assistant integration
- [ ] Kids mode
- [ ] Sound monitoring (YAMNet)

---

## Quick Start (Future README)

```bash
# 1. Install
pip install openocto

# 2. Interactive setup (opens browser wizard)
openocto setup

# 3. Or quick start with defaults
openocto start --persona octo --ai ollama

# 4. Say "Hey Octo!" and ask anything
```

---

## Inspiration

> "The era of smart speakers will evolve into autonomous PCs with AI.
> And they will offer an order of magnitude more capabilities.
> A home media center with AI is a great example.
> And it should be an open-source project, because people
> will want a transparent, reliable solution without surveillance."

---

**Project:** OpenOcto
**Mascot:** 🐙
**Author:** [Rocket Dev](https://rocketdev.tech)
**License:** BSL 1.1
