import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient } from '@/shared/api/client'
import { useAuthStore } from '@/features/auth/store'
import { AICallClient, type AICallStatus } from './ai-call-client'

export type TestCallStatus = AICallStatus | 'idle' | 'error'

interface UseTestCallResult {
  status: TestCallStatus
  error: string | null
  isActive: boolean
  remoteStream: MediaStream | null
  transcript: string[]
  start: () => Promise<void>
  end: () => Promise<void>
}

/**
 * Derive the bare server origin (no `/api/v1` suffix) that AICallClient
 * expects, from the apiClient's configured baseURL.
 */
function deriveServerUrl(): string {
  const resolved = new URL(apiClient.defaults.baseURL ?? '/api/v1', window.location.origin)
  return resolved.origin + resolved.pathname.replace(/\/api\/v1\/?$/, '')
}

const ACTIVE_STATUSES: TestCallStatus[] = [
  'connecting',
  'requesting_microphone',
  'creating_offer',
  'sending_offer',
  'setting_remote_description',
  'connecting_websocket_fallback',
  'connected',
  'remote_track_received',
  'hanging_up',
]

export function useTestCall(agentId: string): UseTestCallResult {
  const clientRef = useRef<AICallClient | null>(null)
  const [status, setStatus] = useState<TestCallStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null)
  const [transcript, setTranscript] = useState<string[]>([])

  const start = useCallback(async () => {
    setError(null)
    setTranscript([])
    setRemoteStream(null)

    const token = useAuthStore.getState().token
    const client = new AICallClient({
      agentId,
      serverUrl: deriveServerUrl(),
      authToken: `Bearer ${token ?? ''}`,
    })

    client.onStatus = (s) => setStatus(s)
    client.onError = (err) => {
      setError(err instanceof Error ? err.message : String(err))
      setStatus('error')
    }
    client.onTrack = (track, streams) => {
      setRemoteStream(streams[0] ?? new MediaStream([track]))
    }
    client.onTranscript = (text) => {
      setTranscript((prev) => [...prev, text])
    }

    clientRef.current = client

    try {
      await client.startCall()
    } catch {
      // onError already captured the failure into state; avoid an unhandled rejection.
    }
  }, [agentId])

  const end = useCallback(async () => {
    if (clientRef.current) {
      await clientRef.current.hangup()
      clientRef.current = null
    }
    setStatus('idle')
    setError(null)
    setRemoteStream(null)
  }, [])

  useEffect(() => {
    return () => {
      void clientRef.current?.hangup()
      clientRef.current = null
    }
  }, [])

  return {
    status,
    error,
    isActive: ACTIVE_STATUSES.includes(status) || status.startsWith('ice_') || status.startsWith('peer_'),
    remoteStream,
    transcript,
    start,
    end,
  }
}
