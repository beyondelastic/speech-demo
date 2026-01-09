// Voice Agent Interface - Client-side JavaScript

class VoiceAgentInterface {
    constructor() {
        this.isRecording = false;
        this.isProcessing = false;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.recognition = null;
        
        // WebSocket streaming
        this.websocket = null;
        this.streamingMode = true; // Enable streaming by default
        this.audioContext = null;
        this.currentPartialText = ''; // Store partial recognition results
        
        // DOM elements
        this.voiceButton = document.getElementById('voiceButton');
        this.chatWindow = document.getElementById('chatWindow');
        this.status = document.getElementById('status');
        this.errorMessage = document.getElementById('errorMessage');
        this.agentIdInput = document.getElementById('agentId');
        this.speechKeyInput = document.getElementById('speechKey');
        this.speechRegionInput = document.getElementById('speechRegion');
        
        this.initializeEventListeners();
        this.loadConfiguration();
    }

    initializeEventListeners() {
        this.voiceButton.addEventListener('click', () => this.toggleRecording());
        
        // Save configuration when changed
        [this.agentIdInput, this.speechKeyInput, this.speechRegionInput].forEach(input => {
            input.addEventListener('change', () => this.saveConfiguration());
        });
    }

    loadConfiguration() {
        // Load from localStorage
        this.agentIdInput.value = localStorage.getItem('agentId') || '';
        this.speechKeyInput.value = localStorage.getItem('speechKey') || '';
        this.speechRegionInput.value = localStorage.getItem('speechRegion') || '';
    }

    saveConfiguration() {
        localStorage.setItem('agentId', this.agentIdInput.value);
        localStorage.setItem('speechKey', this.speechKeyInput.value);
        localStorage.setItem('speechRegion', this.speechRegionInput.value);
    }

    validateConfiguration(requireAgent = true) {
        if (requireAgent && !this.agentIdInput.value) {
            this.showError('Please enter your Agent ID');
            return false;
        }
        // Speech key and region are now optional (will use Foundry credentials)
        return true;
    }

    async toggleRecording() {
        if (this.isProcessing) return;

        // For streaming recognition, we don't need agent ID yet
        // (only needed when sending to agent after recognition)
        if (!this.streamingMode && !this.validateConfiguration()) return;

        if (!this.isRecording) {
            await this.startRecording();
        } else {
            // Just mute/unmute the microphone, don't fully stop
            this.pauseRecording();
        }
    }

    async startRecording() {
        try {
            console.log('[Recording] Starting...');
            this.hideError();
            this.updateStatus('Connecting...', true);
            
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            console.log('[Recording] Microphone access granted');
            
            if (this.streamingMode) {
                console.log('[Recording] Using streaming mode');
                await this.startStreamingRecognition(stream);
            } else {
                console.log('[Recording] Using single-shot mode');
                await this.startSingleShotRecognition(stream);
            }

        } catch (error) {
            console.error('[Recording] Error:', error);
            this.showError('Failed to access microphone. Please check permissions.');
            this.updateStatus('Ready', false);
        }
    }
    
    async startStreamingRecognition(stream) {
        try {
            // Connect to WebSocket
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/speech-stream`;
            this.websocket = new WebSocket(wsUrl);
            
            this.websocket.onopen = async () => {
                console.log('[WebSocket] Connected');
                this.updateStatus('Listening...', true);
                
                // Send configuration
                const config = {
                    type: 'config',
                    speechKey: this.speechKeyInput.value || null,
                    speechRegion: this.speechRegionInput.value || null,
                    agentId: this.agentIdInput.value || null
                };
                console.log('[WebSocket] Sending config:', config);
                this.websocket.send(JSON.stringify(config));
            };
            
            this.websocket.onmessage = (event) => {
                const message = JSON.parse(event.data);
                console.log('[WebSocket] Message:', message);
                
                switch (message.type) {
                    case 'ready':
                        console.log('[WebSocket] Ready to receive audio');
                        break;
                    
                    case 'recognizing':
                        // Show partial results in gray
                        this.updatePartialMessage(message.text);
                        break;
                    
                    case 'recognized':
                        // Show final results in black
                        this.finalizePartialMessage(message.text);
                        break;
                    
                    case 'processing':
                        // User finished speaking, processing with agent
                        this.updateStatus('Processing...', true);
                        this.addMessage('user', message.text);
                        this.currentPartialText = '';
                        break;
                    
                    case 'agent_thinking':
                        // Agent is using tools
                        this.updateStatus(message.message, true);
                        break;
                    
                    case 'agent_response_chunk':
                        // Stream agent response in real-time
                        this.appendAgentResponse(message.text);
                        break;
                    
                    case 'agent_response_complete':
                        // Agent finished responding
                        this.finalizeAgentResponse(message.full_text);
                        this.updateStatus('Agent speaking...', true);
                        // Convert to speech
                        this.textToSpeech(message.full_text).then(() => {
                            // TTS finished, wait for ready_for_next
                            console.log('[TTS] Finished speaking');
                        }).catch(err => {
                            console.error('[TTS] Error:', err);
                            this.updateStatus('Ready', false);
                        });
                        break;
                    
                    case 'ready_for_next':
                        // Server is ready, reconnect for next conversation turn
                        console.log('[WebSocket] Ready for next input, reconnecting...');
                        this.stopStreamingRecognition();
                        this.updateStatus('Restarting...', true);
                        // Give a moment for TTS to finish, then restart
                        setTimeout(() => {
                            if (!this.isRecording) {
                                console.log('[WebSocket] Reconnecting for next turn');
                                this.startRecording();
                            }
                        }, 1000);  // Increased delay to ensure TTS finishes
                        break;
                    
                    case 'session_stopped':
                        console.log('[WebSocket] Session stopped');
                        break;
                    
                    case 'error':
                        console.error('[WebSocket] Error:', message.message);
                        this.showError(message.message);
                        this.updateStatus('Listening...', true);
                        break;
                }
            };
            
            this.websocket.onerror = (error) => {
                console.error('[WebSocket] Error:', error);
                this.showError('WebSocket connection error');
                this.stopStreamingRecognition();
            };
            
            this.websocket.onclose = () => {
                console.log('[WebSocket] Disconnected');
            };
            
            // Set up MediaRecorder for streaming audio chunks
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
            const source = this.audioContext.createMediaStreamSource(stream);
            const processor = this.audioContext.createScriptProcessor(4096, 1, 1);
            
            processor.onaudioprocess = (e) => {
                if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                    const inputData = e.inputBuffer.getChannelData(0);
                    // Convert float32 to int16 PCM
                    const pcmData = new Int16Array(inputData.length);
                    for (let i = 0; i < inputData.length; i++) {
                        const s = Math.max(-1, Math.min(1, inputData[i]));
                        pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                    }
                    this.websocket.send(pcmData.buffer);
                }
            };
            
            source.connect(processor);
            processor.connect(this.audioContext.destination);
            
            // Store references for cleanup
            this.mediaStream = stream;
            this.audioProcessor = processor;
            this.audioSource = source;
            
            this.isRecording = true;
            this.voiceButton.classList.add('recording');
            this.voiceButton.textContent = '⏹️';
            
        } catch (error) {
            console.error('[Streaming] Error:', error);
            this.showError('Failed to start streaming recognition');
            this.updateStatus('Ready', false);
        }
    }
    
    async startSingleShotRecognition(stream) {
        this.mediaRecorder = new MediaRecorder(stream);
        this.audioChunks = [];

        this.mediaRecorder.ondataavailable = (event) => {
            this.audioChunks.push(event.data);
        };

        this.mediaRecorder.onstop = async () => {
            const audioBlob = new Blob(this.audioChunks, { type: 'audio/wav' });
            await this.processAudio(audioBlob);
            
            // Stop all tracks
            stream.getTracks().forEach(track => track.stop());
        };

        this.mediaRecorder.start();
        this.isRecording = true;
        this.voiceButton.classList.add('recording');
        this.voiceButton.textContent = '⏹️';
    }

    async stopRecording() {
        if (this.streamingMode) {
            this.stopStreamingRecognition();
        } else {
            if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
                this.mediaRecorder.stop();
                this.isRecording = false;
                this.voiceButton.classList.remove('recording');
                this.voiceButton.textContent = '🎤';
            }
        }
    }
    
    stopStreamingRecognition() {
        // Cleanup WebSocket
        if (this.websocket) {
            if (this.websocket.readyState === WebSocket.OPEN) {
                this.websocket.send(JSON.stringify({ type: 'stop' }));
            }
            this.websocket.close();
            this.websocket = null;
        }
        
        // Cleanup audio processing
        if (this.audioProcessor) {
            this.audioProcessor.disconnect();
            this.audioProcessor = null;
        }
        if (this.audioSource) {
            this.audioSource.disconnect();
            this.audioSource = null;
        }
        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(track => track.stop());
            this.mediaStream = null;
        }
        
        // Finalize any remaining partial text
        if (this.currentPartialText) {
            this.finalizePartialMessage(this.currentPartialText);
        }
        
        this.isRecording = false;
        this.voiceButton.classList.remove('recording');
        this.voiceButton.textContent = '🎤';
        this.updateStatus('Ready', false);
    }
    
    updatePartialMessage(text) {
        this.currentPartialText = text;
        
        // Find or create partial message element
        let partialElement = document.getElementById('partial-message');
        if (!partialElement) {
            partialElement = document.createElement('div');
            partialElement.id = 'partial-message';
            partialElement.className = 'message user partial';
            partialElement.innerHTML = `
                <div>
                    <div class="message-label">You (speaking...)</div>
                    <div class="message-content" style="color: #999; font-style: italic;"></div>
                </div>
            `;
            this.chatWindow.appendChild(partialElement);
        }
        
        const contentElement = partialElement.querySelector('.message-content');
        contentElement.textContent = text;
        this.chatWindow.scrollTop = this.chatWindow.scrollHeight;
    }
    
    finalizePartialMessage(text) {
        const partialElement = document.getElementById('partial-message');
        if (partialElement) {
            partialElement.remove();
        }
        
        // Don't add a new message if text is empty
        if (text && text.trim()) {
            this.currentPartialText = text;
        }
    }
    
    appendAgentResponse(chunk) {
        // Find or create streaming agent message element
        let agentElement = document.getElementById('streaming-agent-message');
        if (!agentElement) {
            agentElement = document.createElement('div');
            agentElement.id = 'streaming-agent-message';
            agentElement.className = 'message agent';
            agentElement.innerHTML = `
                <div>
                    <div class="message-label">Agent</div>
                    <div class="message-content"></div>
                </div>
            `;
            this.chatWindow.appendChild(agentElement);
        }
        
        const contentElement = agentElement.querySelector('.message-content');
        contentElement.textContent += chunk;
        this.chatWindow.scrollTop = this.chatWindow.scrollHeight;
    }
    
    finalizeAgentResponse(fullText) {
        const streamingElement = document.getElementById('streaming-agent-message');
        if (streamingElement) {
            streamingElement.removeAttribute('id');
        }
    }
    
    pauseRecording() {
        // Visual feedback that mic is muted but still connected
        this.isRecording = false;
        this.voiceButton.classList.remove('recording');
        this.voiceButton.classList.add('paused');
        this.voiceButton.textContent = '🎤';
        this.updateStatus('Paused', false);
    }
    

    async processAudio(audioBlob) {
        this.isProcessing = true;
        this.updateStatus('Processing...', true);

        try {
            // Step 1: Convert speech to text
            const userText = await this.speechToText(audioBlob);
            
            if (!userText) {
                throw new Error('No speech detected');
            }

            this.addMessage('user', userText);

            // Step 2: Send to agent and get response
            const agentResponse = await this.sendToAgent(userText);
            
            this.addMessage('agent', agentResponse);

            // Step 3: Convert agent response to speech and play
            await this.textToSpeech(agentResponse);

            this.updateStatus('Ready', false);

        } catch (error) {
            console.error('Error processing audio:', error);
            this.showError(`Error: ${error.message}`);
            this.updateStatus('Ready', false);
        } finally {
            this.isProcessing = false;
        }
    }

    async speechToText(audioBlob) {
        // Convert audio blob to base64 for sending to backend
        const formData = new FormData();
        formData.append('audio', audioBlob);
        // Only send speech key/region if provided (otherwise backend uses Foundry credentials)
        if (this.speechKeyInput.value) {
            formData.append('speechKey', this.speechKeyInput.value);
        }
        if (this.speechRegionInput.value) {
            formData.append('speechRegion', this.speechRegionInput.value);
        }

        const response = await fetch('/api/speech-to-text', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error('Speech to text conversion failed');
        }

        const data = await response.json();
        return data.text;
    }

    async sendToAgent(userMessage) {
        const response = await fetch('/api/agent/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message: userMessage,
                agentId: this.agentIdInput.value
            })
        });

        if (!response.ok) {
            throw new Error('Agent communication failed');
        }

        const data = await response.json();
        return data.response;
    }

    async textToSpeech(text) {
        const requestBody = { text: text };
        
        // Only send speech key/region if provided (otherwise backend uses Foundry credentials)
        if (this.speechKeyInput.value) {
            requestBody.speechKey = this.speechKeyInput.value;
        }
        if (this.speechRegionInput.value) {
            requestBody.speechRegion = this.speechRegionInput.value;
        }
        
        const response = await fetch('/api/text-to-speech', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            throw new Error('Text to speech conversion failed');
        }

        const audioBlob = await response.blob();
        const audioUrl = URL.createObjectURL(audioBlob);
        const audio = new Audio(audioUrl);
        
        return new Promise((resolve, reject) => {
            audio.onended = resolve;
            audio.onerror = reject;
            audio.play();
        });
    }

    addMessage(sender, text) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender}`;
        
        messageDiv.innerHTML = `
            <div>
                <div class="message-label">${sender === 'user' ? 'You' : 'Agent'}</div>
                <div class="message-content">${this.escapeHtml(text)}</div>
            </div>
        `;
        
        this.chatWindow.appendChild(messageDiv);
        this.chatWindow.scrollTop = this.chatWindow.scrollHeight;
    }

    updateStatus(text, active) {
        this.status.textContent = text;
        if (active) {
            this.status.classList.add('active');
        } else {
            this.status.classList.remove('active');
        }
    }

    showError(message) {
        this.errorMessage.textContent = message;
        this.errorMessage.classList.add('show');
        setTimeout(() => this.hideError(), 5000);
    }

    hideError() {
        this.errorMessage.classList.remove('show');
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize the interface when the page loads
document.addEventListener('DOMContentLoaded', () => {
    new VoiceAgentInterface();
});
