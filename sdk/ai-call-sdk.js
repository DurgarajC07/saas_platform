/**
 * ai-call-sdk.js  —  Browser WebRTC voice-call client SDK
 *
 * Tiny ES-module SDK that connects a browser to the AI Voice SaaS platform
 * via standard WebRTC (ICE / DTLS / SRTP), with an automatic fallback to raw
 * WebSocket PCM when the browser or network does not support WebRTC.
 *
 * Usage
 * -----
 * ```html
 * <script type="module">
 *   import AICallClient from './ai-call-sdk.js';
 *
 *   const client = new AICallClient({
 *     agentId:   '00000000-0000-0000-0000-000000000001',
 *     serverUrl: 'https://api.example.com',
 *     authToken: 'Bearer eyJ...',
 *   });
 *
 *   client.onStatus = (status) => console.log('status:', status);
 *   client.onTrack  = (track, streams) => {
 *     document.getElementById('audio').srcObject = streams[0];
 *   };
 *   client.onError  = (err) => console.error('call error:', err);
 *
 *   await client.startCall();                     // WebRTC with WS fallback
 *   // later …
 *   await client.hangup();
 * </script>
 * ```
 *
 * API
 * ---
 * new AICallClient(options)
 *   options.agentId    {string}  UUID of the agent to call            (required)
 *   options.serverUrl  {string}  Platform API base URL, no trailing / (required)
 *   options.authToken  {string}  Authorization header value            (required)
 *   options.iceTimeout {number}  ms to wait for ICE gathering          (default 5000)
 *   options.sampleRate {number}  getUserMedia sampleRate hint          (default 16000)
 *
 * client.onStatus(status: string)                  — called with lifecycle events
 * client.onTrack(track, streams)                   — called when remote audio track arrives
 * client.onError(error: Error | string)            — called on fatal errors
 * client.onTranscript(text: string)                — called when server sends transcript event
 *
 * client.startCall()  → Promise<void>              — start a WebRTC call (WS fallback if needed)
 * client.hangup()     → Promise<void>              — end the current call
 * client.sessionId    — session ID string once call is established (null before)
 *
 * Transport selection
 * -------------------
 * 1. If RTCPeerConnection is available AND getUserMedia succeeds → WebRTC.
 * 2. Otherwise                                                   → WebSocket PCM.
 *
 * The WebSocket fallback streams raw int16 PCM at 16 kHz—identical to the
 * pipeline service's native WebSocket transport.
 *
 * @module ai-call-sdk
 * @license MIT
 */

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const DEFAULT_ICE_TIMEOUT_MS = 5_000;
const DEFAULT_SAMPLE_RATE    = 16_000;
const DEFAULT_CHANNELS       = 1;
// PCM chunk size for the WebSocket fallback: 20 ms at 16 kHz, mono, int16
const WS_CHUNK_SAMPLES       = 320;   // 320 * 2 bytes = 640 bytes per chunk

// ─────────────────────────────────────────────────────────────────────────────
// AICallClient
// ─────────────────────────────────────────────────────────────────────────────

class AICallClient {
  /**
   * @param {object}  options
   * @param {string}  options.agentId    - UUID of the target agent
   * @param {string}  options.serverUrl  - Platform API base URL (no trailing slash)
   * @param {string}  options.authToken  - Value of the Authorization header
   * @param {number}  [options.iceTimeout=5000]  - ICE gathering timeout (ms)
   * @param {number}  [options.sampleRate=16000] - Audio sample rate
   */
  constructor({ agentId, serverUrl, authToken, iceTimeout, sampleRate } = {}) {
    if (!agentId)    throw new Error('AICallClient: agentId is required');
    if (!serverUrl)  throw new Error('AICallClient: serverUrl is required');
    if (!authToken)  throw new Error('AICallClient: authToken is required');

    this._agentId    = agentId;
    this._serverUrl  = serverUrl.replace(/\/$/, '');
    this._authToken  = authToken;
    this._iceTimeout = iceTimeout ?? DEFAULT_ICE_TIMEOUT_MS;
    this._sampleRate = sampleRate ?? DEFAULT_SAMPLE_RATE;

    /** @type {RTCPeerConnection | null} */
    this._pc         = null;
    /** @type {MediaStream | null} */
    this._localStream = null;
    /** @type {WebSocket | null} */
    this._ws         = null;
    /** @type {ScriptProcessorNode | null} */
    this._scriptNode = null;
    /** @type {AudioContext | null} */
    this._audioCtx   = null;

    /** Session ID returned by the platform after the call is established. */
    this.sessionId = null;

    // ── Event callbacks (set by caller) ──────────────────────────────────────
    /** @type {function(string): void} */
    this.onStatus    = (_status) => {};
    /** @type {function(MediaStreamTrack, readonly MediaStream[]): void} */
    this.onTrack     = (_track, _streams) => {};
    /** @type {function(Error|string): void} */
    this.onError     = (_err) => {};
    /** @type {function(string): void} */
    this.onTranscript = (_text) => {};
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  /**
   * Establish the call.  Tries WebRTC first; falls back to WebSocket if the
   * browser or network cannot support it.
   *
   * @returns {Promise<void>}
   */
  async startCall() {
    this._emit('connecting');
    try {
      if (this._supportsWebRTC()) {
        await this._startWebRTC();
      } else {
        await this._startWebSocket();
      }
    } catch (err) {
      this._emitError(err);
      throw err;
    }
  }

  /**
   * Terminate the current call and release all resources.
   *
   * @returns {Promise<void>}
   */
  async hangup() {
    this._emit('hanging_up');
    this._cleanupWebRTC();
    this._cleanupWebSocket();
    this._releaseLocalStream();
    this.sessionId = null;
    this._emit('disconnected');
  }

  // ── WebRTC path ─────────────────────────────────────────────────────────────

  /**
   * Full WebRTC setup: getUserMedia → createOffer → POST webrtc/connect →
   * setRemoteDescription → wait for connection.
   *
   * @private
   */
  async _startWebRTC() {
    // 1. Capture microphone
    this._emit('requesting_microphone');
    try {
      this._localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate:   this._sampleRate,
          channelCount: DEFAULT_CHANNELS,
          echoCancellation:   true,
          noiseSuppression:   true,
          autoGainControl:    true,
        },
        video: false,
      });
    } catch (err) {
      throw new Error(`Microphone access denied: ${err.message}`);
    }

    // 2. Build RTCPeerConnection with placeholder ICE server list
    //    (the server returns the real list together with its SDP answer)
    this._pc = new RTCPeerConnection({
      iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
    });

    // Add local audio track
    for (const track of this._localStream.getAudioTracks()) {
      this._pc.addTrack(track, this._localStream);
    }

    // Remote audio forwarded to the caller's onTrack handler
    this._pc.ontrack = (event) => {
      this._emit('remote_track_received');
      this.onTrack(event.track, event.streams);
    };

    this._pc.oniceconnectionstatechange = () => {
      const s = this._pc?.iceConnectionState;
      this._emit(`ice_${s}`);
      if (s === 'failed') {
        this._emitError('ICE connection failed — check STUN/TURN configuration');
      }
    };

    this._pc.onconnectionstatechange = () => {
      const s = this._pc?.connectionState;
      this._emit(`peer_${s}`);
      if (s === 'failed' || s === 'closed') {
        this._emitError('RTCPeerConnection closed unexpectedly');
      }
    };

    // 3. Create offer and wait for local ICE candidates
    this._emit('creating_offer');
    const offer = await this._pc.createOffer();
    await this._pc.setLocalDescription(offer);
    await this._waitForIceGathering();

    // 4. POST to platform → pipeline SDP exchange
    this._emit('sending_offer');
    const connectUrl =
      `${this._serverUrl}/api/v1/agents/${this._agentId}/webrtc/connect`;

    let answerData;
    try {
      const resp = await fetch(connectUrl, {
        method: 'POST',
        headers: {
          'Content-Type':  'application/json',
          'Authorization': this._authToken,
        },
        body: JSON.stringify({
          sdp:  this._pc.localDescription.sdp,
          type: this._pc.localDescription.type,
        }),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(`Server returned ${resp.status}: ${detail}`);
      }
      answerData = await resp.json();
    } catch (err) {
      throw new Error(`WebRTC connect request failed: ${err.message}`);
    }

    // Backend responses are Pydantic CamelModels (app/shared/base_schemas.py),
    // which always serialize to camelCase — there's no snake_case variant.
    this.sessionId = answerData.sessionId ?? null;

    // 5. (Optional) Re-configure ICE servers if the server returned TURN entries
    if (Array.isArray(answerData.iceServers) && answerData.iceServers.length) {
      // RTCPeerConnection.setConfiguration is widely supported
      try {
        this._pc.setConfiguration({ iceServers: answerData.iceServers });
      } catch (_) {
        // Non-fatal; ICE is already underway
      }
    }

    // 6. Set remote description (SDP answer from pipeline service)
    this._emit('setting_remote_description');
    await this._pc.setRemoteDescription(
      new RTCSessionDescription({
        sdp:  answerData.sdp,
        type: answerData.type,
      })
    );

    this._emit('connected');
  }

  /**
   * Wait until ICE gathering is complete or the timeout fires.
   * Resolves regardless so that a partial candidate list can still
   * produce a working offer (trickle-ICE style).
   *
   * @private
   * @returns {Promise<void>}
   */
  _waitForIceGathering() {
    return new Promise((resolve) => {
      if (this._pc.iceGatheringState === 'complete') {
        resolve();
        return;
      }
      const timer = setTimeout(resolve, this._iceTimeout);
      this._pc.onicegatheringstatechange = () => {
        if (this._pc?.iceGatheringState === 'complete') {
          clearTimeout(timer);
          resolve();
        }
      };
    });
  }

  // ── WebSocket fallback path ─────────────────────────────────────────────────

  /**
   * @private
   */
  async _startWebSocket() {
    this._emit('connecting_websocket_fallback');

    // Acquire microphone
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      this._localStream = stream;
    } catch (err) {
      throw new Error(`Microphone access denied: ${err.message}`);
    }

    // Build the WebSocket URL from the REST API base (https → wss)
    const wsBase = this._serverUrl
      .replace(/^https:\/\//, 'wss://')
      .replace(/^http:\/\//, 'ws://');

    // We use the test-call endpoint to get a WS URL
    const testCallUrl =
      `${this._serverUrl}/api/v1/agents/${this._agentId}/test-call`;
    let wsUrl;
    try {
      const resp = await fetch(testCallUrl, {
        method: 'POST',
        headers: { 'Authorization': this._authToken },
      });
      if (!resp.ok) {
        throw new Error(`test-call returned ${resp.status}`);
      }
      const data = await resp.json();
      wsUrl = data.wsUrl;
      this.sessionId = data.sessionId ?? null;
    } catch (err) {
      throw new Error(`WebSocket fallback setup failed: ${err.message}`);
    }

    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    this._ws = ws;

    ws.onopen = () => {
      this._emit('connected');
      this._startMicCapture(stream, ws);
    };
    ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const msg = JSON.parse(event.data);
          if (msg.event === 'transcript' && msg.text) {
            this.onTranscript(msg.text);
          }
        } catch (_) { /* ignore malformed JSON */ }
      }
    };
    ws.onerror = (event) => this._emitError('WebSocket error');
    ws.onclose = () => this._emit('disconnected');
  }

  /**
   * Capture microphone audio and stream 20 ms int16 PCM chunks over the WS.
   *
   * @private
   * @param {MediaStream} stream
   * @param {WebSocket}   ws
   */
  _startMicCapture(stream, ws) {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;

    const ctx = new AudioCtx({ sampleRate: this._sampleRate });
    this._audioCtx = ctx;

    const source = ctx.createMediaStreamSource(stream);
    // ScriptProcessorNode is deprecated but still the most portable option
    // for real-time PCM capture.  Buffer size of 4096 ≈ 256 ms; we slice it
    // into 640 B (20 ms) chunks before sending.
    const bufferSize = 4096;
    const scriptNode = ctx.createScriptProcessor(bufferSize, 1, 1);
    this._scriptNode = scriptNode;

    let pcmBuf = new Int16Array(0);

    scriptNode.onaudioprocess = (event) => {
      if (ws.readyState !== WebSocket.OPEN) return;

      // Float32 → Int16
      const floats = event.inputBuffer.getChannelData(0);
      const int16   = new Int16Array(floats.length);
      for (let i = 0; i < floats.length; i++) {
        int16[i] = Math.max(-32768, Math.min(32767, floats[i] * 32768));
      }

      // Concatenate with leftover from previous callback
      const merged = new Int16Array(pcmBuf.length + int16.length);
      merged.set(pcmBuf, 0);
      merged.set(int16, pcmBuf.length);

      // Emit 20 ms chunks
      let offset = 0;
      while (offset + WS_CHUNK_SAMPLES <= merged.length) {
        const chunk = merged.slice(offset, offset + WS_CHUNK_SAMPLES);
        ws.send(chunk.buffer);
        offset += WS_CHUNK_SAMPLES;
      }
      pcmBuf = merged.slice(offset);
    };

    source.connect(scriptNode);
    scriptNode.connect(ctx.destination);
  }

  // ── Feature detection ───────────────────────────────────────────────────────

  /**
   * @private
   * @returns {boolean}
   */
  _supportsWebRTC() {
    return (
      typeof RTCPeerConnection !== 'undefined' &&
      typeof navigator.mediaDevices?.getUserMedia === 'function'
    );
  }

  // ── Cleanup helpers ─────────────────────────────────────────────────────────

  /** @private */
  _cleanupWebRTC() {
    if (this._pc) {
      try { this._pc.close(); } catch (_) {}
      this._pc = null;
    }
  }

  /** @private */
  _cleanupWebSocket() {
    if (this._scriptNode) {
      try { this._scriptNode.disconnect(); } catch (_) {}
      this._scriptNode = null;
    }
    if (this._audioCtx) {
      try { this._audioCtx.close(); } catch (_) {}
      this._audioCtx = null;
    }
    if (this._ws) {
      try { this._ws.close(); } catch (_) {}
      this._ws = null;
    }
  }

  /** @private */
  _releaseLocalStream() {
    if (this._localStream) {
      for (const track of this._localStream.getTracks()) {
        track.stop();
      }
      this._localStream = null;
    }
  }

  // ── Event helpers ───────────────────────────────────────────────────────────

  /** @private */
  _emit(status) {
    try { this.onStatus(status); } catch (_) {}
  }

  /** @private */
  _emitError(err) {
    try { this.onError(err instanceof Error ? err : new Error(String(err))); } catch (_) {}
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Exports
// ─────────────────────────────────────────────────────────────────────────────

export { AICallClient };
export default AICallClient;
