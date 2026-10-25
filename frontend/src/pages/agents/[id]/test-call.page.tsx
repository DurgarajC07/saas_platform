import { useEffect, useRef } from 'react'
import { useParams } from '@tanstack/react-router'
import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Button } from '@/shared/components/ui/button'
import { Badge, type BadgeProps } from '@/shared/components/ui/badge'
import { Alert, AlertTitle, AlertDescription } from '@/shared/components/ui/alert'
import { useAgent } from '@/features/agents/hooks'
import { useTestCall, type TestCallStatus } from '@/features/test-call/useTestCall'

// ─────────────────────────────────────────────────────────────────────────────
// Status → friendly label / badge variant
// ─────────────────────────────────────────────────────────────────────────────
function describeStatus(status: TestCallStatus): { label: string; variant: BadgeProps['variant'] } {
  if (status === 'idle') return { label: 'Ready', variant: 'secondary' }
  if (status === 'disconnected') return { label: 'Disconnected', variant: 'secondary' }
  if (status === 'hanging_up') return { label: 'Ending…', variant: 'outline' }
  if (
    status === 'connecting' ||
    status === 'requesting_microphone' ||
    status === 'creating_offer' ||
    status === 'sending_offer' ||
    status === 'setting_remote_description' ||
    status === 'connecting_websocket_fallback'
  ) {
    return { label: 'Connecting…', variant: 'outline' }
  }
  if (
    status === 'connected' ||
    status === 'remote_track_received' ||
    status === 'ice_connected' ||
    status === 'ice_completed' ||
    status === 'peer_connected'
  ) {
    return { label: 'Connected', variant: 'success' }
  }
  if (
    status === 'error' ||
    status === 'ice_failed' ||
    status === 'ice_disconnected' ||
    status === 'peer_failed' ||
    status === 'peer_closed' ||
    status === 'peer_disconnected'
  ) {
    return { label: 'Error', variant: 'destructive' }
  }
  if (status.startsWith('ice_') || status.startsWith('peer_')) {
    return { label: 'Connecting…', variant: 'outline' }
  }
  return { label: status, variant: 'outline' }
}

export function AgentTestCallPage() {
  const { agentId } = useParams({ from: '/agents/$agentId/test-call' })
  const { data: agent } = useAgent(agentId)
  const { status, error, isActive, remoteStream, transcript, start, end } = useTestCall(agentId)
  const audioRef = useRef<HTMLAudioElement>(null)

  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.srcObject = remoteStream
    }
  }, [remoteStream])

  const { label, variant } = describeStatus(status)
  const isConnected = label === 'Connected'
  const isConnecting = isActive && !isConnected && status !== 'hanging_up'

  return (
    <PageContainer maxWidth="md">
      <PageHeader
        title="Test Call"
        description={agent ? `Make a test call with "${agent.name}".` : 'Make a test call with this agent.'}
      />

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Call controls</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <Badge variant={variant}>{label}</Badge>
            <span className="text-xs text-muted-foreground">{status}</span>
          </div>

          {error && (
            <Alert variant="destructive">
              <AlertTitle>Call error</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {remoteStream && isConnected && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="inline-block size-2 animate-pulse rounded-full bg-green-500" />
              Agent audio active
            </div>
          )}

          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <audio ref={audioRef} autoPlay className="hidden" />

          <div>
            {isActive ? (
              <Button
                variant="destructive"
                onClick={() => void end()}
                disabled={status === 'hanging_up'}
              >
                End Call
              </Button>
            ) : (
              <Button onClick={() => void start()} disabled={isConnecting}>
                Start Test Call
              </Button>
            )}
          </div>

          {transcript.length > 0 && (
            <div className="max-h-48 overflow-y-auto rounded-md border bg-muted/30 p-3 text-sm">
              {transcript.map((line, i) => (
                <p key={i} className="text-muted-foreground">
                  {line}
                </p>
              ))}
            </div>
          )}

          <p className="text-xs text-muted-foreground">
            Starting a test call requires microphone access — your browser will prompt for
            permission.
          </p>
        </CardContent>
      </Card>
    </PageContainer>
  )
}
