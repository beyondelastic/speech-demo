// OR Voice Control — Client-side JavaScript

class VoiceAgentInterface {
    constructor() {
        this.isRecording = false;
        this.isProcessing = false;
        this.websocket = null;
        this.audioContext = null;
        this.currentPartialText = '';

        this.voiceButton = document.getElementById('voiceButton');
        this.chatWindow = document.getElementById('chatWindow');
        this.status = document.getElementById('status');
        this.latencyBadge = document.getElementById('latencyBadge');
        this.errorMessage = document.getElementById('errorMessage');

        this.voiceButton.addEventListener('click', () => this.toggleRecording());
    }

    async toggleRecording() {
        if (this.isProcessing) return;
        if (!this.isRecording) {
            if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                this.resumeRecording();
            } else {
                await this.startRecording();
            }
        } else {
            this.pauseRecording();
        }
    }

    async startRecording() {
        try {
            this.hideError();
            this.updateStatus('Connecting...', true);
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            await this.startStreaming(stream);
        } catch (e) {
            this.showError('Failed to access microphone.');
            this.updateStatus('Ready', false);
        }
    }

    async startStreaming(stream) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/speech-stream`;
        this.websocket = new WebSocket(wsUrl);

        this.websocket.onopen = () => {
            this.updateStatus('Listening...', true);
            this.websocket.send(JSON.stringify({ type: 'config' }));
        };

        this.websocket.onmessage = (event) => {
            if (event.data instanceof Blob) {
                this.updateStatus('Agent speaking...', true);
                this.queueAudioUrl(URL.createObjectURL(event.data));
                return;
            }
            const msg = JSON.parse(event.data);

            switch (msg.type) {
                case 'ready':
                    break;
                case 'wake_word_waiting':
                    this.voiceButton.classList.remove('wake-active');
                    this.updateStatus(`Say "${msg.wake_word}" to start...`, true);
                    break;
                case 'wake_word_detected':
                    this.voiceButton.classList.add('wake-active');
                    this.updateStatus('Listening for command...', true);
                    break;
                case 'recognizing':
                    this.updatePartialMessage(msg.text);
                    break;
                case 'recognized':
                    this.finalizePartialMessage(msg.text);
                    break;
                case 'processing':
                    this.voiceButton.classList.remove('wake-active');
                    this.updateStatus('Processing...', true);
                    this.addMessage('user', msg.text);
                    this.currentPartialText = '';
                    break;
                case 'agent_thinking':
                    this.updateStatus(msg.message, true);
                    break;
                case 'agent_response_chunk':
                    this.appendAgentResponse(msg.text);
                    break;
                case 'agent_response_complete':
                    this.finalizeAgentResponse(msg.full_text);
                    if (msg.pipeline_ms != null) this.showLatency(msg.pipeline_ms);
                    if (window._lightPanel) window._lightPanel.fetchState();
                    if (window._videoPanel) {
                        window._videoPanel.fetchState();
                        setTimeout(() => window._videoPanel.fetchState(), 500);
                    }
                    break;
                case 'ready_for_next':
                    this.updateStatus('Listening...', true);
                    break;
                case 'error':
                    this.showError(msg.message);
                    this.updateStatus('Listening...', true);
                    break;
            }
        };

        this.websocket.onerror = () => {
            this.showError('WebSocket connection error');
            this.stopStreaming();
        };

        this.websocket.onclose = () => {};

        // PCM audio streaming
        this.audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        const source = this.audioContext.createMediaStreamSource(stream);
        const processor = this.audioContext.createScriptProcessor(4096, 1, 1);

        processor.onaudioprocess = (e) => {
            if (this.isRecording && this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                const input = e.inputBuffer.getChannelData(0);
                const pcm = new Int16Array(input.length);
                for (let i = 0; i < input.length; i++) {
                    const s = Math.max(-1, Math.min(1, input[i]));
                    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }
                this.websocket.send(pcm.buffer);
            }
        };

        source.connect(processor);
        processor.connect(this.audioContext.destination);

        this.mediaStream = stream;
        this.audioProcessor = processor;
        this.audioSource = source;
        this.isRecording = true;
        this.voiceButton.classList.add('recording');
        this.voiceButton.textContent = '⏹️';
    }

    stopStreaming() {
        if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
            this.websocket.send(JSON.stringify({ type: 'stop' }));
        }
        if (this.audioProcessor) { this.audioProcessor.disconnect(); this.audioProcessor = null; }
        if (this.audioSource) { this.audioSource.disconnect(); this.audioSource = null; }
        if (this.audioContext) { this.audioContext.close(); this.audioContext = null; }
        if (this.mediaStream) { this.mediaStream.getTracks().forEach(t => t.stop()); this.mediaStream = null; }
        if (this.currentPartialText) this.finalizePartialMessage(this.currentPartialText);
        this.isRecording = false;
        this.voiceButton.classList.remove('recording');
        this.voiceButton.textContent = '🎤';
        this.updateStatus('Ready', false);
    }

    pauseRecording() {
        this.isRecording = false;
        this.voiceButton.classList.remove('recording');
        this.voiceButton.classList.add('paused');
        this.voiceButton.textContent = '🎤';
        this.updateStatus('Paused', false);
    }

    resumeRecording() {
        this.isRecording = true;
        this.voiceButton.classList.remove('paused');
        this.voiceButton.classList.add('recording');
        this.voiceButton.textContent = '⏹️';
        this.updateStatus('Listening...', true);
    }

    // --- Chat UI ---

    updatePartialMessage(text) {
        this.currentPartialText = text;
        let el = document.getElementById('partial-message');
        if (!el) {
            el = document.createElement('div');
            el.id = 'partial-message';
            el.className = 'message user partial';
            el.innerHTML = '<div><div class="message-label">You (speaking...)</div><div class="message-content" style="color:#999;font-style:italic;"></div></div>';
            this.chatWindow.appendChild(el);
        }
        el.querySelector('.message-content').textContent = text;
        this.chatWindow.scrollTop = this.chatWindow.scrollHeight;
    }

    finalizePartialMessage(text) {
        const el = document.getElementById('partial-message');
        if (el) el.remove();
        if (text && text.trim()) this.currentPartialText = text;
    }

    appendAgentResponse(chunk) {
        let el = document.getElementById('streaming-agent-message');
        if (!el) {
            el = document.createElement('div');
            el.id = 'streaming-agent-message';
            el.className = 'message agent';
            el.innerHTML = '<div><div class="message-label">Agent</div><div class="message-content"></div></div>';
            this.chatWindow.appendChild(el);
        }
        el.querySelector('.message-content').textContent += chunk;
        this.chatWindow.scrollTop = this.chatWindow.scrollHeight;
    }

    finalizeAgentResponse(fullText) {
        const el = document.getElementById('streaming-agent-message');
        if (el) el.removeAttribute('id');
    }

    addMessage(sender, text) {
        const div = document.createElement('div');
        div.className = `message ${sender}`;
        div.innerHTML = `<div><div class="message-label">${sender === 'user' ? 'You' : 'Agent'}</div><div class="message-content">${this.escapeHtml(text)}</div></div>`;
        this.chatWindow.appendChild(div);
        this.chatWindow.scrollTop = this.chatWindow.scrollHeight;
    }

    // --- Audio Playback Queue ---

    queueAudioUrl(url) {
        if (!this._audioQueue) this._audioQueue = [];
        this._audioQueue.push(url);
        if (!this._audioPlaying) this._playNext();
    }

    async _playNext() {
        if (!this._audioQueue || this._audioQueue.length === 0) {
            this._audioPlaying = false;
            if (this.isRecording || (this.websocket && this.websocket.readyState === WebSocket.OPEN)) {
                this.updateStatus('Listening...', true);
            }
            return;
        }
        this._audioPlaying = true;
        const url = this._audioQueue.shift();
        try {
            const audio = new Audio(url);
            await new Promise((resolve, reject) => {
                audio.onended = () => { URL.revokeObjectURL(url); resolve(); };
                audio.onerror = (e) => { URL.revokeObjectURL(url); reject(e); };
                audio.play();
            });
        } catch (e) {
            console.error('[TTS] Error:', e);
        }
        this._playNext();
    }

    // --- Helpers ---

    updateStatus(text, active) {
        this.status.textContent = text;
        this.status.classList.toggle('active', active);
    }

    showLatency(ms) {
        this.latencyBadge.textContent = `${ms}ms`;
        this.latencyBadge.classList.add('show');
        clearTimeout(this._latencyTimer);
        this._latencyTimer = setTimeout(() => {
            this.latencyBadge.classList.remove('show');
        }, 8000);
    }

    showError(msg) {
        this.errorMessage.textContent = msg;
        this.errorMessage.classList.add('show');
        setTimeout(() => this.hideError(), 5000);
    }

    hideError() { this.errorMessage.classList.remove('show'); }

    escapeHtml(text) {
        const d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    }
}


// --- OR Light Panel ---

class ORLightPanel {
    constructor() {
        this._lastStateStr = '';
        this.scenePresets = {
            full_surgery: { surgical_main: { power: true, brightness: 100 }, surgical_secondary: { power: true, brightness: 90 }, ambient_ceiling: { power: true, brightness: 30 }, ambient_wall: { power: true, brightness: 20 }, task_monitor: { power: true, brightness: 70 } },
            laparoscopy: { surgical_main: { power: false, brightness: 0 }, surgical_secondary: { power: false, brightness: 0 }, ambient_ceiling: { power: true, brightness: 10 }, ambient_wall: { power: true, brightness: 10 }, task_monitor: { power: true, brightness: 100 } },
            prep: { surgical_main: { power: true, brightness: 100 }, surgical_secondary: { power: true, brightness: 100 }, ambient_ceiling: { power: true, brightness: 100 }, ambient_wall: { power: true, brightness: 100 }, task_monitor: { power: true, brightness: 80 } },
            closing: { surgical_main: { power: true, brightness: 80 }, surgical_secondary: { power: true, brightness: 60 }, ambient_ceiling: { power: true, brightness: 50 }, ambient_wall: { power: true, brightness: 40 }, task_monitor: { power: true, brightness: 60 } },
            emergency: { surgical_main: { power: true, brightness: 100 }, surgical_secondary: { power: true, brightness: 100 }, ambient_ceiling: { power: true, brightness: 100 }, ambient_wall: { power: true, brightness: 100 }, task_monitor: { power: true, brightness: 100 } },
            standby: { surgical_main: { power: false, brightness: 0 }, surgical_secondary: { power: false, brightness: 0 }, ambient_ceiling: { power: true, brightness: 20 }, ambient_wall: { power: true, brightness: 15 }, task_monitor: { power: false, brightness: 0 } },
        };
        this.startPolling();
    }

    startPolling() {
        this.fetchState();
        this.pollInterval = setInterval(() => this.fetchState(), 3000);
    }

    async fetchState() {
        try {
            const r = await fetch('http://localhost:8932/api/lights/state');
            if (!r.ok) return;
            const state = await r.json();
            const str = JSON.stringify(state);
            if (str !== this._lastStateStr) {
                this._lastStateStr = str;
                this.currentState = state;
                this.render();
            }
        } catch (e) { /* lights API may not be running */ }
    }

    render() {
        const ids = ['surgical_main', 'surgical_secondary', 'ambient_ceiling', 'ambient_wall', 'task_monitor'];
        for (const id of ids) {
            const data = this.currentState[id];
            if (!data) continue;
            const el = document.getElementById(`light-${id}`);
            if (!el) continue;
            const isOn = data.power === 'ON';
            const brightness = data.brightness;
            const colorTemp = data.color_temp_kelvin || 4500;
            el.classList.toggle('off', !isOn);
            const valueEl = el.querySelector('.light-value');
            if (valueEl) valueEl.textContent = isOn ? `${brightness}%` : 'OFF';
            let rgb;
            if (data.color_hex) {
                const hex = data.color_hex.replace('#', '');
                rgb = { r: parseInt(hex.substring(0,2),16), g: parseInt(hex.substring(2,4),16), b: parseInt(hex.substring(4,6),16) };
            } else {
                rgb = this.kelvinToRGB(colorTemp);
            }
            const iconEl = el.querySelector('.light-icon');
            const glowEl = el.querySelector('.light-glow');
            if (isOn && brightness > 0) {
                const a = brightness / 100;
                const gs = 60 + brightness * 1.2;
                const c = `${rgb.r},${rgb.g},${rgb.b}`;
                iconEl.style.background = `rgba(${c},${0.3 + a * 0.7})`;
                iconEl.style.boxShadow = `0 0 ${brightness / 3}px rgba(${c},${a})`;
                glowEl.style.width = `${gs}px`; glowEl.style.height = `${gs}px`;
                glowEl.style.top = `${-(gs - 56) / 2}px`; glowEl.style.left = `${(56 - gs) / 2}px`;
                glowEl.style.background = `radial-gradient(circle, rgba(${c},${a * 0.35}) 0%, transparent 70%)`;
            } else {
                iconEl.style.background = '#374151'; iconEl.style.boxShadow = 'none';
                glowEl.style.width = '0px'; glowEl.style.height = '0px'; glowEl.style.background = 'none';
            }
        }
        this.renderDetails();
        this.detectScene();
    }

    renderDetails() {
        const c = document.getElementById('lightDetails');
        if (!c) return;
        let html = '';
        for (const [id, d] of Object.entries(this.currentState)) {
            const on = d.power === 'ON';
            html += `<div class="light-detail-row"><span class="light-detail-name">${d.name}</span><div class="light-detail-status"><span class="${on ? 'on' : 'off'}">${on ? d.brightness + '%' : 'OFF'}</span><span>${d.color ? d.color.replace('_',' ') : d.color_temp_kelvin + 'K'}</span></div></div>`;
        }
        c.innerHTML = html;
    }

    detectScene() {
        let matched = null;
        for (const [sid, preset] of Object.entries(this.scenePresets)) {
            let ok = true;
            for (const [lid, exp] of Object.entries(preset)) {
                const a = this.currentState[lid];
                if (!a || (a.power === 'ON') !== exp.power || a.brightness !== exp.brightness) { ok = false; break; }
            }
            if (ok) { matched = sid; break; }
        }
        document.querySelectorAll('.scene-badge').forEach(b => b.classList.toggle('active', b.dataset.scene === matched));
    }

    kelvinToRGB(k) {
        const t = k / 100;
        let r, g, b;
        if (t <= 66) { r = 255; g = Math.min(255, Math.max(0, 99.47 * Math.log(t) - 161.12)); }
        else { r = Math.min(255, Math.max(0, 329.7 * Math.pow(t - 60, -0.133))); g = Math.min(255, Math.max(0, 288.12 * Math.pow(t - 60, -0.0755))); }
        if (t >= 66) b = 255;
        else if (t <= 19) b = 0;
        else b = Math.min(255, Math.max(0, 138.52 * Math.log(t - 10) - 305.04));
        return { r: Math.round(r), g: Math.round(g), b: Math.round(b) };
    }
}


// --- Video Panel ---

class ORVideoPanel {
    constructor() {
        this._lastStr = '';
        this._timer = null;
        this._startTime = null;
        this.startPolling();
    }

    startPolling() {
        this.fetchState();
        this.pollInterval = setInterval(() => this.fetchState(), 2000);
    }

    async fetchState() {
        try {
            const r = await fetch('http://localhost:8933/api/video/state');
            if (!r.ok) return;
            const state = await r.json();
            const str = JSON.stringify(state);
            if (str !== this._lastStr) {
                this._lastStr = str;
                this.render(state);
            }
        } catch (e) { /* video API may not be running */ }
    }

    render(s) {
        const dot = document.getElementById('recDot');
        const label = document.getElementById('recLabel');
        const badge = document.getElementById('videoStatusBadge');
        const duration = document.getElementById('videoDuration');
        const snaps = document.getElementById('videoSnapshots');
        const total = document.getElementById('videoTotal');

        if (s.recording) {
            dot.classList.add('recording');
            label.textContent = 'REC';
            label.classList.add('recording');
            badge.textContent = 'RECORDING';
            badge.className = 'video-status-badge recording';
            duration.classList.add('active');
            // Live duration counter
            if (!this._timer) {
                this._startTime = Date.now() - (s.duration_seconds * 1000);
                this._timer = setInterval(() => {
                    const elapsed = Math.round((Date.now() - this._startTime) / 1000);
                    duration.textContent = elapsed;
                }, 1000);
            }
        } else {
            dot.classList.remove('recording');
            label.textContent = 'IDLE';
            label.classList.remove('recording');
            badge.textContent = 'IDLE';
            badge.className = 'video-status-badge idle';
            duration.classList.remove('active');
            if (this._timer) {
                clearInterval(this._timer);
                this._timer = null;
                this._startTime = null;
            }
            duration.textContent = Math.round(s.duration_seconds);
        }
        snaps.textContent = s.snapshot_count;
        total.textContent = s.total_recordings;
    }
}


// --- Init ---

document.addEventListener('DOMContentLoaded', () => {
    new VoiceAgentInterface();
    window._lightPanel = new ORLightPanel();
    window._videoPanel = new ORVideoPanel();
});
