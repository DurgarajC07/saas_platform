import { useState, useRef } from 'react'
import { useParams } from '@tanstack/react-router'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { UploadIcon, LinkIcon, Trash2Icon, FileTextIcon, FilesIcon } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

import { PageContainer } from '@/shared/components/layout/PageContainer'
import { PageHeader } from '@/shared/components/layout/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Badge } from '@/shared/components/ui/badge'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import { EmptyState } from '@/shared/components/data-display/EmptyState'
import { ConfirmDialog } from '@/shared/components/feedback/ConfirmDialog'
import { cn } from '@/shared/lib/utils'

import {
  useKnowledgeBase,
  useUploadKbDocument,
  useIngestUrl,
  useDeleteKbDocument,
} from '@/features/knowledge-base/hooks'
import { urlIngestSchema, type UrlIngestInput, type KbStatus } from '@/features/knowledge-base/schemas'

const ACCEPTED_EXTENSIONS = '.pdf,.docx,.txt,.md,.csv'

// ─── Status badge ─────────────────────────────────────────────────────────────
function KbStatusBadge({ status }: { status: KbStatus }) {
  if (status === 'completed') {
    return (
      <Badge className="border-transparent bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100">
        Completed
      </Badge>
    )
  }
  if (status === 'failed') {
    return <Badge variant="destructive">Failed</Badge>
  }
  if (status === 'processing') {
    return (
      <Badge variant="default" className="gap-1.5">
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
        Processing
      </Badge>
    )
  }
  return <Badge variant="outline">Pending</Badge>
}

// ─── Page ─────────────────────────────────────────────────────────────────────
export function AgentKnowledgeBasePage() {
  const { agentId } = useParams({ from: '/agents/$agentId/knowledge-base' })

  const { data, isLoading } = useKnowledgeBase(agentId)
  const uploadDocument = useUploadKbDocument(agentId)
  const ingestUrl = useIngestUrl(agentId)
  const deleteDocument = useDeleteKbDocument(agentId)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null)

  const urlForm = useForm<UrlIngestInput>({
    resolver: zodResolver(urlIngestSchema),
    defaultValues: { url: '' },
  })

  const documents = data?.documents ?? []

  function handleUpload() {
    if (!selectedFile) return
    uploadDocument.mutate(
      { file: selectedFile },
      {
        onSuccess: () => {
          setSelectedFile(null)
          if (fileInputRef.current) fileInputRef.current.value = ''
        },
      },
    )
  }

  function handleIngestUrl(values: UrlIngestInput) {
    ingestUrl.mutate(values.url, {
      onSuccess: () => {
        urlForm.reset()
      },
    })
  }

  function handleConfirmDelete() {
    if (!deleteTarget) return
    deleteDocument.mutate(deleteTarget.id, {
      onSuccess: () => {
        setDeleteTarget(null)
      },
    })
  }

  return (
    <PageContainer>
      <PageHeader
        title="Knowledge Base"
        description="Upload documents or link sources for your agent to answer from."
      />

      <div className="mt-6 space-y-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* File upload */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Upload a document</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Label htmlFor="kb-file">File (pdf, docx, txt, md, csv)</Label>
              <input
                id="kb-file"
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_EXTENSIONS}
                onChange={(e) => {
                  setSelectedFile(e.target.files?.[0] ?? null)
                }}
                className={cn(
                  'flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors',
                  'file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                )}
              />
              <Button
                onClick={handleUpload}
                disabled={!selectedFile || uploadDocument.isPending}
                loading={uploadDocument.isPending}
              >
                <UploadIcon className="mr-2 h-4 w-4" />
                Upload
              </Button>
            </CardContent>
          </Card>

          {/* URL / YouTube ingestion */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Add a URL or YouTube link</CardTitle>
            </CardHeader>
            <CardContent>
              <form
                onSubmit={(e) => {
                  void urlForm.handleSubmit(handleIngestUrl)(e)
                }}
                className="space-y-3"
              >
                <Label htmlFor="kb-url">Link</Label>
                <Input
                  id="kb-url"
                  placeholder="https://example.com/article or a YouTube link"
                  {...urlForm.register('url')}
                />
                {urlForm.formState.errors.url && (
                  <p className="text-destructive text-sm">
                    {urlForm.formState.errors.url.message}
                  </p>
                )}
                <Button type="submit" disabled={ingestUrl.isPending} loading={ingestUrl.isPending}>
                  <LinkIcon className="mr-2 h-4 w-4" />
                  Add link
                </Button>
              </form>
            </CardContent>
          </Card>
        </div>

        {/* Documents list */}
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : documents.length === 0 ? (
          <EmptyState
            icon={FilesIcon}
            title="No documents yet"
            description="Upload a file or add a link above to build this agent's knowledge base."
          />
        ) : (
          <div className="overflow-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Chunks</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <FileTextIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <div>
                          <p className="font-medium">{doc.fileName}</p>
                          {doc.status === 'failed' && doc.errorMessage && (
                            <p className="text-destructive text-xs">{doc.errorMessage}</p>
                          )}
                          {doc.sourceUrl && (
                            <p className="text-muted-foreground text-xs">{doc.sourceUrl}</p>
                          )}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="uppercase">
                        {doc.fileType}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <KbStatusBadge status={doc.status} />
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {doc.chunkCount ?? '—'}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {formatDistanceToNow(new Date(doc.createdAt), { addSuffix: true })}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Delete document"
                        onClick={() => {
                          setDeleteTarget({ id: doc.id, name: doc.fileName })
                        }}
                      >
                        <Trash2Icon className="h-4 w-4 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
        onConfirm={handleConfirmDelete}
        title="Delete document?"
        description={
          deleteTarget
            ? `"${deleteTarget.name}" will be permanently removed from the knowledge base.`
            : undefined
        }
        confirmLabel="Delete"
        variant="destructive"
        loading={deleteDocument.isPending}
      />
    </PageContainer>
  )
}
