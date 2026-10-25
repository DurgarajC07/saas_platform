import { useParams } from '@tanstack/react-router'
import { format } from 'date-fns'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Badge } from '@/shared/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { EmptyState } from '@/shared/components/data-display/EmptyState'
import { getErrorMessage } from '@/shared/api/error-handler'
import { useCall, useRecordingUrl } from '@/features/calls/hooks'
import { AlertTriangleIcon } from 'lucide-react'

function formatDuration(sec: number | null): string {
  if (sec === null) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatTimestamp(value: string | null): string {
  if (!value) return '—'
  return format(new Date(value), 'MMM d, yyyy h:mm:ss a')
}

function directionVariant(direction: string): 'info' | 'secondary' {
  return direction === 'inbound' ? 'info' : 'secondary'
}

function statusVariant(status: string): 'success' | 'destructive' | 'warning' | 'secondary' {
  if (status === 'completed') return 'success'
  if (status === 'failed' || status === 'no-answer') return 'destructive'
  if (status === 'connected') return 'warning'
  return 'secondary'
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}

export function CallDetailPage() {
  const { callId } = useParams({ from: '/calls/$callId' })
  const { data: call, isLoading, isError, error } = useCall(callId)

  const hasRecording = Boolean(call?.recordingUrl)
  const { data: recording, isLoading: isRecordingLoading } = useRecordingUrl(
    callId,
    hasRecording,
  )

  return (
    <PageContainer>
      <PageHeader title="Call Detail" description="Full call recording, transcript and metadata." />

      {isLoading ? (
        <div className="mt-6 space-y-4">
          <Skeleton className="h-40 w-full rounded-xl" />
          <Skeleton className="h-40 w-full rounded-xl" />
        </div>
      ) : isError || !call ? (
        <div className="mt-6">
          <EmptyState
            icon={AlertTriangleIcon}
            title="Couldn't load this call"
            description={getErrorMessage(error)}
          />
        </div>
      ) : (
        <div className="mt-6 space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Overview</CardTitle>
              </CardHeader>
              <CardContent className="divide-y">
                <DetailRow label="Caller ID" value={call.callerId ?? '—'} />
                <DetailRow
                  label="Direction"
                  value={
                    <Badge variant={directionVariant(call.direction)}>{call.direction}</Badge>
                  }
                />
                <DetailRow
                  label="Status"
                  value={<Badge variant={statusVariant(call.status)}>{call.status}</Badge>}
                />
                <DetailRow label="Transport" value={call.transport} />
                <DetailRow label="Started" value={formatTimestamp(call.startedAt)} />
                <DetailRow label="Ended" value={formatTimestamp(call.endedAt)} />
                <DetailRow label="Duration" value={formatDuration(call.durationSec)} />
                <DetailRow
                  label="Cost"
                  value={call.costCredits !== null ? `${call.costCredits} credits` : '—'}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Latency Breakdown</CardTitle>
              </CardHeader>
              <CardContent className="divide-y">
                <DetailRow
                  label="STT"
                  value={call.sttMs !== null ? `${call.sttMs} ms` : '—'}
                />
                <DetailRow
                  label="LLM TTFT"
                  value={call.llmTtftMs !== null ? `${call.llmTtftMs} ms` : '—'}
                />
                <DetailRow
                  label="TTS TTFB"
                  value={call.ttsTtfbMs !== null ? `${call.ttsTtfbMs} ms` : '—'}
                />
              </CardContent>
            </Card>
          </div>

          {hasRecording && (
            <Card>
              <CardHeader>
                <CardTitle>Recording</CardTitle>
              </CardHeader>
              <CardContent>
                {isRecordingLoading ? (
                  <Skeleton className="h-10 w-full rounded-md" />
                ) : recording ? (
                  // eslint-disable-next-line jsx-a11y/media-has-caption
                  <audio controls src={recording.url} className="w-full" />
                ) : (
                  <p className="text-sm text-muted-foreground">Recording unavailable.</p>
                )}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Transcript</CardTitle>
            </CardHeader>
            <CardContent>
              {call.transcript ? (
                <pre className="whitespace-pre-wrap font-sans text-sm">{call.transcript}</pre>
              ) : (
                <p className="text-sm text-muted-foreground">No transcript available.</p>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </PageContainer>
  )
}
