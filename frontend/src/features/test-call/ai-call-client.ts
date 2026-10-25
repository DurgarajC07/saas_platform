/**
 * ai-call-client.ts — Browser WebRTC voice-call client.
 *
 * TypeScript port of `sdk/ai-call-sdk.js` (`AICallClient`). Behavior, status
 * strings, and transport-selection logic are kept faithful to the original
 * ES-module SDK; only types have been added.
 *
 * Transport selection
 * -------------------
 * 1. If RTCPeerConnection is available AND getUserMedia succeeds → WebRTC.
 * 2. Otherwise                                                   → WebSocket PCM.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const DEFAULT_ICE_TIMEOUT_MS = 5_000
const DEFAULT_SAMPLE_RATE = 16_000
const DEFAULT_CHANNELS = 1
// PCM chunk size for the WebSocket fallback: 20 ms at 16 kHz, mono, int16
const WS_CHUNK_SAMPLES = 320 // 320 * 2 bytes = 640 bytes per chunk

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface AICallClientOptions {
  /** UUID of the target agent */
  agentId: string
  /** Platform API base URL (no trailing slash) */
  serverUrl: string
  /** Value of the Authorization header */
  authToken: string
  /** ICE gathering timeout (ms) — default 5000 */
  iceTimeout?: number
  /** Audio sample rate — default 16000 */
  sampleRate?: number
}

export type AICallStatus =
  | 'connecting'
  | 'requesting_microphone'
  | 'creating_offer'
  | 'sending_offer'
  | 'setting_remote_description'
  | 'connected'
  | 'remote_track_received'
  | 'hanging_up'
  | 'disconnected'
  | 'connecting_websocket_fallback'
  | `ice_${string}`
  | `peer_${string}`

// Backend responses are Pydantic `CamelModel`s (app/shared/base_schemas.py),
// which always serialize to camelCase — there is no snake_case variant to
// guess between.
interface WebRTCConnectResponse {
  sessionId: string
  iceServers?: RTCIceServer[]
  sdp: string
  type: RTCSdpType
}

interface TestCallResponse {
  wsUrl: string
  sessionId: string
}

// ─────────────────────────────────────────────────────────────────────────────
// AICallClient
// ─────────────────────────────────────────────────────────────────────────────

export class AICallClient {
  private readonly _agentId: string
  private readonly _serverUrl: string
  private readonly _authToken: string
  private readonly _iceTimeout: number
  private readonly _sampleRate: number

  private _pc: RTCPeerConnection | null = null
  private _localStream: MediaStream | null = null
  private _ws: WebSocket | null = null
  private _scriptNode: ScriptProcessorNode | null = null
  private _audioCtx: AudioContext | null = null

  /** Session ID returned by the platform after the call is established. */
  sessionId: string | null = null

  // ── Event callbacks (set by caller) ──────────────────────────────────────
  onStatus: (status: AICallStatus) => void = () => {}
  onTrack: (track: MediaStreamTrack, streams: readonly MediaStream[]) => void = () => {}
  onError: (err: Error) => void = () => {}
  onTranscript: (text: string) => void = () => {}

  constructor({ agentId, serverUrl, authToken, iceTimeout, sampleRate }: AICallClientOptions) {
    if (!agentId) throw new Error('AICallClient: agentId is required')
    if (!serverUrl) throw new Error('AICallClient: serverUrl is required')
    if (!authToken) throw new Error('AICallClient: authToken is required')

    this._agentId = agentId
    this._serverUrl = serverUrl.replace(/\/$/, '')
    this._authToken = authToken
    this._iceTimeout = iceTimeout ?? DEFAULT_ICE_TIMEOUT_MS
    this._sampleRate = sampleRate ?? DEFAULT_SAMPLE_RATE
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  /**
   * Establish the call. Tries WebRTC first; falls back to WebSocket if the
   * browser or network cannot support it.
   */
  async startCall(): Promise<void> {
    this._emit('connecting')
    try {
      if (this._supportsWebRTC()) {
        await this._startWebRTC()
      } else {
        await this._startWebSocket()
      }
    } catch (err) {
      this._emitError(err)
      throw err
    }
  }

  /**
   * Terminate the current call and release all resources.
   */
  async hangup(): Promise<void> {
    this._emit('hanging_up')
    this._cleanupWebRTC()
    this._cleanupWebSocket()
    this._releaseLocalStream()
    this.sessionId = null
    this._emit('disconnected')
  }

  // ── WebRTC path ─────────────────────────────────────────────────────────────

  /**
   * Full WebRTC setup: getUserMedia → createOffer → POST webrtc/connect →
   * setRemoteDescription → wait for connection.
   */
  private async _startWebRTC(): Promise<void> {
    // 1. Capture microphone
    this._emit('requesting_microphone')
    try {
      this._localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: this._sampleRate,
          channelCount: DEFAULT_CHANNELS,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      })
    } catch (err) {
      throw new Error(`Microphone access denied: ${(err as Error).message}`)
    }

    // 2. Build RTCPeerConnection with placeholder ICE server list
    //    (the server returns the real list together with its SDP answer)
    const pc = new RTCPeerConnection({
      iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
    })
    this._pc = pc

    // Add local audio track
    for (const track of this._localStream.getAudioTracks()) {
      pc.addTrack(track, this._localStream)
    }

    // Remote audio forwarded to the caller's onTrack handler
    pc.ontrack = (event) => {
      this._emit('remote_track_received')
      this.onTrack(event.track, event.streams)
    }

    pc.oniceconnectionstatechange = () => {
      const s = this._pc?.iceConnectionState
      this._emit(`ice_${s}`)
      if (s === 'failed') {
        this._emitError('ICE connection failed — check STUN/TURN configuration')
      }
    }

    pc.onconnectionstatechange = () => {
      const s = this._pc?.connectionState
      this._emit(`peer_${s}`)
      if (s === 'failed' || s === 'closed') {
        this._emitError('RTCPeerConnection closed unexpectedly')
      }
    }

    // 3. Create offer and wait for local ICE candidates
    this._emit('creating_offer')
    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    await this._waitForIceGathering()

    // 4. POST to platform → pipeline SDP exchange
    this._emit('sending_offer')
    const connectUrl = `${this._serverUrl}/api/v1/agents/${this._agentId}/webrtc/connect`

    let answerData: WebRTCConnectResponse
    try {
      const resp = await fetch(connectUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: this._authToken,
        },
        body: JSON.stringify({
          sdp: pc.localDescription?.sdp,
          type: pc.localDescription?.type,
        }),
      })
      if (!resp.ok) {
        const detail = await resp.text()
        throw new Error(`Server returned ${resp.status}: ${detail}`)
      }
      answerData = (await resp.json()) as WebRTCConnectResponse
    } catch (err) {
      throw new Error(`WebRTC connect request failed: ${(err as Error).message}`)
    }

    this.sessionId = answerData.sessionId

    // 5. (Optional) Re-configure ICE servers if the server returned TURN entries
    if (Array.isArray(answerData.iceServers) && answerData.iceServers.length) {
      // RTCPeerConnection.setConfiguration is widely supported
      try {
        pc.setConfiguration({ iceServers: answerData.iceServers })
      } catch {
        // Non-fatal; ICE is already underway
      }
    }

    // 6. Set remote description (SDP answer from pipeline service)
    this._emit('setting_remote_description')
    await pc.setRemoteDescription(
      new RTCSessionDescription({
        sdp: answerData.sdp,
        type: answerData.type,
      }),
    )

    this._emit('connected')
  }

  /**
   * Wait until ICE gathering is complete or the timeout fires.
   * Resolves regardless so that a partial candidate list can still
   * produce a working offer (trickle-ICE style).
   */
  private _waitForIceGathering(): Promise<void> {
    return new Promise((resolve) => {
      const pc = this._pc
      if (!pc) {
        resolve()
        return
      }
      if (pc.iceGatheringState === 'complete') {
        resolve()
        return
      }
      const timer = setTimeout(resolve, this._iceTimeout)
      pc.onicegatheringstatechange = () => {
        if (this._pc?.iceGatheringState === 'complete') {
          clearTimeout(timer)
          resolve()
        }
      }
    })
  }

  // ── WebSocket fallback path ─────────────────────────────────────────────────

  private async _startWebSocket(): Promise<void> {
    this._emit('connecting_websocket_fallback')

    // Acquire microphone
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      this._localStream = stream
    } catch (err) {
      throw new Error(`Microphone access denied: ${(err as Error).message}`)
    }

    // We use the test-call endpoint to get a WS URL
    const testCallUrl = `${this._serverUrl}/api/v1/agents/${this._agentId}/test-call`
    let wsUrl: string
    try {
      const resp = await fetch(testCallUrl, {
        method: 'POST',
        headers: { Authorization: this._authToken },
      })
      if (!resp.ok) {
        throw new Error(`test-call returned ${resp.status}`)
      }
      const data = (await resp.json()) as TestCallResponse
      wsUrl = data.wsUrl
      this.sessionId = data.sessionId
    } catch (err) {
      throw new Error(`WebSocket fallback setup failed: ${(err as Error).message}`)
    }

    const ws = new WebSocket(wsUrl)
    ws.binaryType = 'arraybuffer'
    this._ws = ws

    ws.onopen = () => {
      this._emit('connected')
      this._startMicCapture(stream, ws)
    }
    ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const msg = JSON.parse(event.data) as { event?: string; text?: string }
          if (msg.event === 'transcript' && msg.text) {
            this.onTranscript(msg.text)
          }
        } catch {
          /* ignore malformed JSON */
        }
      }
    }
    ws.onerror = () => this._emitError('WebSocket error')
    ws.onclose = () => this._emit('disconnected')
  }

  /**
   * Capture microphone audio and stream 20 ms int16 PCM chunks over the WS.
   */
  private _startMicCapture(stream: MediaStream, ws: WebSocket): void {
    const AudioCtx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AudioCtx) return

    const ctx = new AudioCtx({ sampleRate: this._sampleRate })
    this._audioCtx = ctx

    const source = ctx.createMediaStreamSource(stream)
    // ScriptProcessorNode is deprecated but still the most portable option
    // for real-time PCM capture.  Buffer size of 4096 ≈ 256 ms; we slice it
    // into 640 B (20 ms) chunks before sending.
    const bufferSize = 4096
    const scriptNode = ctx.createScriptProcessor(bufferSize, 1, 1)
    this._scriptNode = scriptNode

    let pcmBuf = new Int16Array(0)

    scriptNode.onaudioprocess = (event) => {
      if (ws.readyState !== WebSocket.OPEN) return

      // Float32 → Int16
      const floats = event.inputBuffer.getChannelData(0)
      const int16 = new Int16Array(floats.length)
      for (let i = 0; i < floats.length; i++) {
        int16[i] = Math.max(-32768, Math.min(32767, floats[i] * 32768))
      }

      // Concatenate with leftover from previous callback
      const merged = new Int16Array(pcmBuf.length + int16.length)
      merged.set(pcmBuf, 0)
      merged.set(int16, pcmBuf.length)

      // Emit 20 ms chunks
      let offset = 0
      while (offset + WS_CHUNK_SAMPLES <= merged.length) {
        const chunk = merged.slice(offset, offset + WS_CHUNK_SAMPLES)
        ws.send(chunk.buffer)
        offset += WS_CHUNK_SAMPLES
      }
      pcmBuf = merged.slice(offset)
    }

    source.connect(scriptNode)
    scriptNode.connect(ctx.destination)
  }

  // ── Feature detection ───────────────────────────────────────────────────────

  private _supportsWebRTC(): boolean {
    return (
      typeof RTCPeerConnection !== 'undefined' &&
      typeof navigator.mediaDevices?.getUserMedia === 'function'
    )
  }

  // ── Cleanup helpers ─────────────────────────────────────────────────────────

  private _cleanupWebRTC(): void {
    if (this._pc) {
      try {
        this._pc.close()
      } catch {
        /* noop */
      }
      this._pc = null
    }
  }

  private _cleanupWebSocket(): void {
    if (this._scriptNode) {
      try {
        this._scriptNode.disconnect()
      } catch {
        /* noop */
      }
      this._scriptNode = null
    }
    if (this._audioCtx) {
      try {
        void this._audioCtx.close()
      } catch {
        /* noop */
      }
      this._audioCtx = null
    }
    if (this._ws) {
      try {
        this._ws.close()
      } catch {
        /* noop */
      }
      this._ws = null
    }
  }

  private _releaseLocalStream(): void {
    if (this._localStream) {
      for (const track of this._localStream.getTracks()) {
        track.stop()
      }
      this._localStream = null
    }
  }

  // ── Event helpers ───────────────────────────────────────────────────────────

  private _emit(status: string): void {
    try {
      this.onStatus(status as AICallStatus)
    } catch {
      /* noop */
    }
  }

  private _emitError(err: unknown): void {
    try {
      this.onError(err instanceof Error ? err : new Error(String(err)))
    } catch {
      /* noop */
    }
  }
}

export default AICallClient
