import { apiClient } from '@/shared/api/client'
import type {
  CreateOrgInput,
  UpdateOrgInput,
  InviteMemberInput,
  UpdateMemberRoleInput,
  AddDomainInput,
  OrgResponse,
  MemberResponse,
  MemberListResponse,
  InvitationResponse,
  DomainResponse,
} from './schemas'

interface MessageResponse {
  message: string
}

// ─────────────────────────────────────────────────────────────────────────────
// Org API calls — all endpoints under /organizations
// ─────────────────────────────────────────────────────────────────────────────

export const orgApi = {
  // ── Organizations ──────────────────────────────────────────────────────────

  /** POST /organizations */
  createOrg: async (body: CreateOrgInput): Promise<OrgResponse> => {
    const { data } = await apiClient.post<OrgResponse>('/organizations', body)
    return data
  },

  /** GET /organizations/:slug */
  getOrg: async (slug: string): Promise<OrgResponse> => {
    const { data } = await apiClient.get<OrgResponse>(`/organizations/${slug}`)
    return data
  },

  /** PATCH /organizations/:orgId */
  updateOrg: async (orgId: string, body: UpdateOrgInput): Promise<OrgResponse> => {
    const { data } = await apiClient.patch<OrgResponse>(`/organizations/${orgId}`, body)
    return data
  },

  /** DELETE /organizations/:orgId */
  deleteOrg: async (orgId: string): Promise<void> => {
    await apiClient.delete(`/organizations/${orgId}`)
  },

  // ── Members ────────────────────────────────────────────────────────────────

  /** GET /organizations/:orgId/members */
  listMembers: async (
    orgId: string,
    params?: { page?: number; pageSize?: number },
  ): Promise<MemberListResponse> => {
    const { data } = await apiClient.get<MemberListResponse>(`/organizations/${orgId}/members`, {
      params,
    })
    return data
  },

  /** DELETE /organizations/:orgId/members/:uid */
  removeMember: async (orgId: string, uid: string): Promise<void> => {
    await apiClient.delete(`/organizations/${orgId}/members/${uid}`)
  },

  /** PATCH /organizations/:orgId/members/:uid/role */
  updateMemberRole: async (
    orgId: string,
    uid: string,
    body: UpdateMemberRoleInput,
  ): Promise<MemberResponse> => {
    const { data } = await apiClient.patch<MemberResponse>(
      `/organizations/${orgId}/members/${uid}/role`,
      body,
    )
    return data
  },

  // ── Invitations ────────────────────────────────────────────────────────────

  /** POST /organizations/:orgId/invitations */
  inviteMember: async (orgId: string, body: InviteMemberInput): Promise<InvitationResponse> => {
    const { data } = await apiClient.post<InvitationResponse>(
      `/organizations/${orgId}/invitations`,
      body,
    )
    return data
  },

  /** GET /organizations/:orgId/invitations */
  listInvitations: async (orgId: string): Promise<InvitationResponse[]> => {
    const { data } = await apiClient.get<InvitationResponse[]>(
      `/organizations/${orgId}/invitations`,
    )
    return data
  },

  /** DELETE /organizations/:orgId/invitations/:invitationId */
  revokeInvitation: async (orgId: string, invitationId: string): Promise<MessageResponse> => {
    const { data } = await apiClient.delete<MessageResponse>(
      `/organizations/${orgId}/invitations/${invitationId}`,
    )
    return data
  },

  /** POST /invitations/accept */
  acceptInvitation: async (token: string): Promise<OrgResponse> => {
    const { data } = await apiClient.post<OrgResponse>('/invitations/accept', { token })
    return data
  },

  // ── Domains ────────────────────────────────────────────────────────────────

  /** GET /organizations/:orgId/domains */
  listDomains: async (orgId: string): Promise<DomainResponse[]> => {
    const { data } = await apiClient.get<DomainResponse[]>(`/organizations/${orgId}/domains`)
    return data
  },

  /** POST /organizations/:orgId/domains */
  addDomain: async (orgId: string, body: AddDomainInput): Promise<DomainResponse> => {
    const { data } = await apiClient.post<DomainResponse>(`/organizations/${orgId}/domains`, body)
    return data
  },

  /** DELETE /organizations/:orgId/domains/:domainId */
  deleteDomain: async (orgId: string, domainId: string): Promise<void> => {
    await apiClient.delete(`/organizations/${orgId}/domains/${domainId}`)
  },

  /** POST /organizations/:orgId/domains/:domainId/verify */
  verifyDomain: async (orgId: string, domainId: string): Promise<DomainResponse> => {
    const { data } = await apiClient.post<DomainResponse>(
      `/organizations/${orgId}/domains/${domainId}/verify`,
    )
    return data
  },
}
