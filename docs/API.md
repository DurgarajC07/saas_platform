# VoiceSaaS Platform — Frontend Integration Guide

**Base URL:** `http://localhost:8000` (dev) · `https://api.yourdomain.com` (prod)  
**API version prefix:** `/api/v1`  
**Interactive docs:** `GET /docs` (Swagger UI) · `GET /redoc`

---

## Table of Contents

1. [Authentication & Headers](#1-authentication--headers)
2. [Error Envelope](#2-error-envelope)
3. [Pagination](#3-pagination)
4. [Auth Module](#4-auth-module)
5. [Tenancy (Organizations)](#5-tenancy-organizations)
6. [RBAC (Roles & Permissions)](#6-rbac-roles--permissions)
7. [Billing](#7-billing)
8. [Feature Flags](#8-feature-flags)
9. [Agents](#9-agents)
10. [Calls & Call Logs](#10-calls--call-logs)
11. [Dashboard & Analytics](#11-dashboard--analytics)
12. [Notifications](#12-notifications)
13. [Files](#13-files)
14. [API Keys](#14-api-keys)
15. [Webhooks](#15-webhooks)
16. [Audit Logs](#16-audit-logs)
17. [Security](#17-security)
18. [System](#18-system)
19. [Real-Time: SSE Streams](#19-real-time-sse-streams)
20. [Twilio Webhook Callbacks](#20-twilio-webhook-callbacks)
21. [WebRTC Integration](#21-webrtc-integration)
22. [SDK Reference](#22-sdk-reference)

---

## 1. Authentication & Headers

### Required headers on every protected request

```
Authorization: Bearer <access_token>
X-Org-ID:      <organization_uuid>
Content-Type:  application/json
```

### Token lifecycle

| Token | Lifetime | Stored in |
|-------|----------|-----------|
| `access_token` | 30 min | Memory / httpOnly cookie |
| `refresh_token` | 7 days | httpOnly cookie (recommended) |

### Login flow

```
POST /api/v1/auth/login  →  { access_token, refresh_token, token_type }
                                        ↓
              Use access_token as  Authorization: Bearer <token>
                                        ↓
              When expired (401) →  POST /api/v1/auth/refresh
```

### Example fetch wrapper

```js
async function apiFetch(path, options = {}) {
  const res = await fetch(`/api/v1${path}`, {
    ...options,
    headers: {
      'Authorization': `Bearer ${getAccessToken()}`,
      'X-Org-ID':      getCurrentOrgId(),
      'Content-Type':  'application/json',
      ...options.headers,
    },
  });

  if (res.status === 401) {
    await refreshToken();  // call POST /auth/refresh
    return apiFetch(path, options);  // retry once
  }
  return res;
}
```

---

## 2. Error Envelope

Every error response has the same shape:

```json
{
  "error": {
    "code":       "NOT_FOUND",
    "message":    "The requested resource was not found",
    "request_id": "4f2e1a8b-..."
  }
}
```

### Error codes reference

| HTTP | `code` | When |
|------|--------|------|
| 400 | `BAD_REQUEST` | Malformed request, invalid parameter |
| 401 | `UNAUTHORIZED` | Missing / expired token |
| 401 | `HTTP_ERROR` | Twilio HMAC validation failed |
| 403 | `FORBIDDEN` | Valid token but no permission / feature gate |
| 404 | `NOT_FOUND` | Resource doesn't exist or doesn't belong to org |
| 409 | `CONFLICT` | Duplicate resource (email, slug, phone number) |
| 422 | `VALIDATION_ERROR` | Field-level validation failures (detail is readable string) |
| 429 | `RATE_LIMITED` | Too many requests |
| 503 | `SERVICE_UNAVAILABLE` | Pipeline down, GPU VRAM exhausted |
| 500 | `INTERNAL_ERROR` | Unexpected server error |

### Checking errors in JS

```js
const res = await apiFetch('/agents', { method: 'GET' });
if (!res.ok) {
  const { error } = await res.json();
  console.error(error.code, error.message);  // "NOT_FOUND", "Agent … not found"
}
```

---

## 3. Pagination

All list endpoints return a `pagination` object:

```json
{
  "items": [...],
  "pagination": {
    "page":       1,
    "pageSize":   20,
    "totalItems": 147,
    "totalPages": 8,
    "hasNext":    true,
    "hasPrev":    false
  }
}
```

Query parameters: `?page=2&page_size=50`

---

## 4. Auth Module

**Prefix:** `/api/v1/auth`

---

### `POST /register`

Create a new user account and organisation.

**No auth required.**

**Request body:**
```json
{
  "email":     "alice@example.com",
  "password":  "Str0ngPass!",
  "fullName":  "Alice Smith",
  "orgName":   "Acme Corp",
  "orgSlug":   "acme"
}
```

**Response `201`:**
```json
{
  "id":           "uuid",
  "email":        "alice@example.com",
  "fullName":     "Alice Smith",
  "isVerified":   false,
  "createdAt":    "2026-03-08T10:00:00Z"
}
```

**Errors:**
| Code | Meaning |
|------|---------|
| 409 `CONFLICT` | Email already registered |
| 422 `VALIDATION_ERROR` | Password too weak, invalid email |

---

### `GET /verify-email?token=<token>`

Verify email address from the link in the welcome email.

**No auth required.**

**Response `200`:**
```json
{ "verified": true }
```

**Errors:** `400` – token invalid or expired.

---

### `POST /login`

Exchange credentials for tokens.

**No auth required.**

**Request body:**
```json
{
  "email":    "alice@example.com",
  "password": "Str0ngPass!"
}
```

**Response `200`:**
```json
{
  "accessToken":  "eyJhbGci...",
  "refreshToken": "eyJhbGci...",
  "tokenType":    "bearer",
  "expiresIn":    1800,
  "user": {
    "id":         "uuid",
    "email":      "alice@example.com",
    "fullName":   "Alice Smith",
    "isVerified": true
  }
}
```

**Errors:**
| Code | Meaning |
|------|---------|
| 401 `UNAUTHORIZED` | Wrong password |
| 403 `FORBIDDEN` | Account disabled |
| 404 `NOT_FOUND` | Email not registered |

> **2FA:** If the user has TOTP enabled, the response returns `requiresMfa: true` and a temporary `mfaToken`. Pass the code to `POST /2fa/verify`.

---

### `POST /login/form`

OAuth2-compatible form-body login (for Swagger UI "Authorize" button).

**No auth required.** `Content-Type: application/x-www-form-urlencoded`

```
username=alice%40example.com&password=Str0ngPass%21
```

Returns same body as `POST /login`.

---

### `POST /refresh`

Exchange a refresh token for a new access token.

**No auth required.**

**Request body:**
```json
{ "refreshToken": "eyJhbGci..." }
```

**Response `200`:**
```json
{
  "accessToken":  "eyJhbGci...",
  "refreshToken": "eyJhbGci...",
  "tokenType":    "bearer",
  "expiresIn":    1800
}
```

**Errors:** `401` – refresh token expired or revoked.

---

### `POST /logout`

Revoke the current session.

**Auth required.**

**Request body:** *(empty)*

**Response `200`:**
```json
{ "loggedOut": true }
```

---

### `POST /forgot-password`

Send a password reset email.

**No auth required.**

**Request body:**
```json
{ "email": "alice@example.com" }
```

**Response `200`:**
```json
{ "sent": true }
```

Always returns `200` to avoid user enumeration.

---

### `POST /reset-password`

Set a new password using the reset token from email.

**No auth required.**

**Request body:**
```json
{
  "token":       "<token_from_email>",
  "newPassword": "NewStr0ng!"
}
```

**Response `200`:**
```json
{ "reset": true }
```

**Errors:** `400` – token expired or already used. `422` – new password too weak.

---

### `GET /me`

Get the current authenticated user's profile.

**Auth required.**

**Response `200`:**
```json
{
  "id":            "uuid",
  "email":         "alice@example.com",
  "fullName":      "Alice Smith",
  "avatarUrl":     null,
  "isVerified":    true,
  "isSuperuser":   false,
  "createdAt":     "2026-03-08T10:00:00Z",
  "updatedAt":     "2026-03-08T10:00:00Z"
}
```

---

### `POST /password/change`

Change password while logged in.

**Auth required.**

**Request body:**
```json
{
  "oldPassword": "current",
  "newPassword": "NewStr0ng!"
}
```

**Response `200`:**
```json
{ "changed": true }
```

**Errors:** `400` – old password incorrect.

---

### `GET /sessions`

List all active sessions for the current user.

**Auth required.**

**Response `200`:**
```json
{
  "sessions": [
    {
      "id":          "uuid",
      "deviceInfo":  "Chrome / macOS",
      "ipAddress":   "1.2.3.4",
      "isCurrent":   true,
      "createdAt":   "2026-03-08T09:00:00Z",
      "lastUsedAt":  "2026-03-08T10:30:00Z"
    }
  ]
}
```

---

### `DELETE /sessions/{session_id}`

Revoke a specific session.

**Auth required.**

**Response `200`:**
```json
{ "revoked": true }
```

---

### `DELETE /sessions`

Revoke all sessions except the current one.

**Auth required.**

**Response `200`:**
```json
{ "revokedCount": 3 }
```

---

### `GET /oauth/{provider}`

Begin OAuth2 login flow. `provider` = `google` | `github`.

**No auth required.**

Redirects the browser to the provider consent page. After consent, the provider redirects to the callback URL below.

---

### `GET /oauth/{provider}/callback`

OAuth2 callback. Called by the provider — do **not** call directly.

On success, redirects to the frontend with `?access_token=...&refresh_token=...`.

---

### 2FA Endpoints

#### `POST /2fa/setup`

Generate a TOTP secret. Returns a QR code URI to display in the UI.

**Auth required.**

**Response `200`:**
```json
{
  "secret":      "BASE32SECRET",
  "qrCodeUri":   "otpauth://totp/VoiceSaaS:alice%40example.com?secret=...&issuer=VoiceSaaS",
  "backupCodes": ["ABCD-1234", "EFGH-5678", "..."]
}
```

#### `POST /2fa/confirm`

Confirm the TOTP code to activate 2FA.

**Auth required.**

**Request body:**
```json
{ "code": "123456" }
```

**Response `200`:**
```json
{ "enabled": true }
```

**Errors:** `400` – wrong code.

#### `POST /2fa/verify`

Verify 2FA during login (after receiving `requiresMfa: true`).

**No auth required.**

**Request body:**
```json
{
  "mfaToken": "<temp_token_from_login>",
  "code":     "123456"
}
```

**Response `200`:** Full token pair (same as `/login`).

#### `POST /2fa/backup`

Use a backup code instead of TOTP.

**No auth required.**

**Request body:**
```json
{
  "mfaToken":   "<temp_token_from_login>",
  "backupCode": "ABCD-1234"
}
```

**Response `200`:** Full token pair.

#### `DELETE /2fa/disable`

Turn off 2FA.

**Auth required.**

**Response `200`:**
```json
{ "disabled": true }
```

---

## 5. Tenancy (Organizations)

**Prefix:** `/api/v1`

All endpoints require `Authorization: Bearer <token>`.

---

### `POST /organizations`

Create a new organization.

**Request body:**
```json
{
  "name": "Acme Corp",
  "slug": "acme",
  "logoUrl": null,
  "timezone": "UTC"
}
```

**Response `201`:**
```json
{
  "id":          "uuid",
  "name":        "Acme Corp",
  "slug":        "acme",
  "logoUrl":     null,
  "timezone":    "UTC",
  "isActive":    true,
  "createdAt":   "2026-03-08T10:00:00Z",
  "updatedAt":   "2026-03-08T10:00:00Z"
}
```

**Errors:** `409` – slug already taken.

---

### `GET /organizations/{slug}`

Get organization by slug.

**Response `200`:** Same as create response above.  
**Errors:** `404` – not found.

---

### `PATCH /organizations/{org_id}`

Update organization details.

**Request body (all optional):**
```json
{
  "name":    "Acme Corp v2",
  "logoUrl": "https://cdn.example.com/logo.png",
  "timezone": "America/New_York"
}
```

**Response `200`:** Updated org object.

---

### `DELETE /organizations/{org_id}`

Delete an organization. Requires owner role.

**Response `200`:**
```json
{ "deleted": true }
```

---

### `GET /organizations/{org_id}/members`

List all members of the organization.

**Response `200`:**
```json
{
  "members": [
    {
      "id":       "uuid",
      "userId":   "uuid",
      "email":    "alice@example.com",
      "fullName": "Alice Smith",
      "role":     "admin",
      "joinedAt": "2026-03-08T10:00:00Z"
    }
  ],
  "total": 1
}
```

---

### `DELETE /organizations/{org_id}/members/{user_id}`

Remove a member from the organization.

**Response `200`:**
```json
{ "removed": true }
```

**Errors:** `403` – cannot remove the owner. `404` – member not found.

---

### `PATCH /organizations/{org_id}/members/{user_id}/role`

Change a member's base role.

**Request body:**
```json
{ "role": "admin" }
```

Accepted values: `"owner"` | `"admin"` | `"member"` | `"viewer"`

**Response `200`:** Updated member object.

---

### `POST /organizations/{org_id}/invitations`

Invite a user by email.

**Request body:**
```json
{
  "email": "colleague@example.com",
  "role":  "member"
}
```

**Response `201`:**
```json
{
  "id":        "uuid",
  "email":     "colleague@example.com",
  "role":      "member",
  "token":     "inv_...",
  "expiresAt": "2026-03-15T10:00:00Z",
  "createdAt": "2026-03-08T10:00:00Z"
}
```

**Errors:** `409` – already a member or invitation pending.

---

### `GET /organizations/{org_id}/invitations`

List pending invitations.

**Response `200`:**
```json
{
  "invitations": [{ "id": "uuid", "email": "...", "role": "member", "expiresAt": "...", "createdAt": "..." }],
  "total": 1
}
```

---

### `DELETE /organizations/{org_id}/invitations/{invitation_id}`

Cancel a pending invitation.

**Response `200`:**
```json
{ "cancelled": true }
```

---

### `POST /invitations/accept`

Accept an invitation (called by invited user after clicking email link).

**Auth required** (user must be logged in or just registered).

**Request body:**
```json
{ "token": "<inv_token_from_email>" }
```

**Response `200`:**
```json
{ "joined": true, "organizationId": "uuid" }
```

**Errors:** `400` – token expired or invalid. `409` – already a member.

---

### Domain Verification

#### `POST /organizations/{org_id}/domains`

Add a domain for SSO / email routing.

**Request body:**
```json
{ "domain": "acme.com" }
```

**Response `201`:**
```json
{
  "id":           "uuid",
  "domain":       "acme.com",
  "isVerified":   false,
  "verifyToken":  "voicesaas-verify-abc123",
  "createdAt":    "2026-03-08T10:00:00Z"
}
```

Add a DNS TXT record `voicesaas-verify-abc123` to verify ownership.

#### `GET /organizations/{org_id}/domains`

**Response `200`:**
```json
{ "domains": [{ "id": "uuid", "domain": "acme.com", "isVerified": false, "verifyToken": "..." }] }
```

#### `DELETE /organizations/{org_id}/domains/{domain_id}`

**Response `200`:** `{ "deleted": true }`

#### `POST /organizations/{org_id}/domains/{domain_id}/verify`

Trigger DNS TXT check and mark as verified.

**Response `200`:**
```json
{ "verified": true }
```

**Errors:** `400` – DNS record not found yet.

---

## 6. RBAC (Roles & Permissions)

**Prefix:** `/api/v1/rbac`

---

### `GET /roles`

List all roles in the current organization.

**Response `200`:**
```json
{
  "roles": [
    {
      "id":             "uuid",
      "name":           "support",
      "displayName":    "Support Agent",
      "description":    "Can view calls only",
      "organizationId": "uuid",
      "isSystemRole":   false,
      "isDefault":      false,
      "priority":       10,
      "createdAt":      "...",
      "updatedAt":      "..."
    }
  ],
  "total": 1
}
```

---

### `POST /roles`

Create a custom role.

**Request body:**
```json
{
  "name":        "support",
  "displayName": "Support Agent",
  "description": "Can view calls and audit logs",
  "priority":    10
}
```

**Response `201`:** Role object (see above).  
**Errors:** `409` – role name already exists in org.

---

### `PATCH /roles/{role_id}`

Update a custom role.

**Request body (all optional):**
```json
{
  "displayName": "Senior Support Agent",
  "priority":    20
}
```

**Response `200`:** Updated role object.

---

### `DELETE /roles/{role_id}`

Delete a custom role.

**Response `200`:** `{ "deleted": true }`  
**Errors:** `403` – cannot delete system roles. `409` – role is assigned to members.

---

### `GET /roles/{role_id}/permissions`

Get all permissions assigned to a role.

**Response `200`:**
```json
{
  "roleId": "uuid",
  "permissions": [
    {
      "id":          "uuid",
      "name":        "agents.agent.read",
      "displayName": "View Agents",
      "module":      "agents",
      "resource":    "agent",
      "action":      "read",
      "createdAt":   "...",
      "updatedAt":   "..."
    }
  ]
}
```

---

### `PUT /roles/{role_id}/permissions`

Replace all permissions for a role (full replacement, not merge).

**Request body:**
```json
{
  "permissionIds": ["uuid-1", "uuid-2", "uuid-3"]
}
```

**Response `200`:** Updated permissions list.

---

### `GET /permissions`

List all available permissions, grouped by module.

**Response `200`:**
```json
{
  "groups": [
    {
      "module": "agents",
      "permissions": [
        { "id": "uuid", "name": "agents.agent.read", "action": "read", "resource": "agent", ... }
      ]
    },
    { "module": "billing", "permissions": [...] }
  ],
  "total": 42
}
```

---

### `GET /members/{member_id}/roles`

List roles assigned to a member.

**Response `200`:**
```json
{
  "organizationUserId": "uuid",
  "roles": [
    {
      "organizationUserId": "uuid",
      "role":               { ...RoleResponse },
      "assignedAt":         "...",
      "assignedBy":         "uuid"
    }
  ]
}
```

---

### `PUT /members/{member_id}/roles/{role_id}`

Assign a role to a member.

**Response `200`:** MemberRoleResponse.

---

### `DELETE /members/{member_id}/roles/{role_id}`

Remove a role from a member.

**Response `200`:** `{ "removed": true }`

---

## 7. Billing

**Prefix:** `/api/v1/billing`

---

### `GET /plans`

List all available plans. **Public — no auth required.**

**Response `200`:**
```json
{
  "plans": [
    {
      "id":            "uuid",
      "name":          "Starter",
      "slug":          "starter",
      "description":   "Up to 500 call minutes/month",
      "priceMonthly":  29.00,
      "priceYearly":   290.00,
      "currency":      "USD",
      "trialDays":     14,
      "maxSeats":      5,
      "maxStorageMb":  1024,
      "displayOrder":  1,
      "features":      { "ai.agents.max": 3, "ai.pstn.enabled": true },
      "createdAt":     "...",
      "updatedAt":     "..."
    }
  ],
  "total": 3
}
```

---

### `GET /plans/{plan_id}`

Get a single plan.

**Response `200`:** Single plan object (see above).

---

### `POST /plans` *(Admin)*

Create a plan. Requires superuser.

**Request body:**
```json
{
  "name":          "Enterprise",
  "slug":          "enterprise",
  "description":   "Unlimited calls",
  "priceMonthly":  299.00,
  "priceYearly":   2990.00,
  "currency":      "USD",
  "trialDays":     30,
  "maxSeats":      null,
  "maxStorageMb":  null,
  "displayOrder":  3,
  "features":      {}
}
```

**Response `201`:** Plan object.

---

### `PATCH /plans/{plan_id}` *(Admin)*

**Request body (all optional):**
```json
{
  "priceMonthly": 349.00,
  "trialDays":    0,
  "isActive":     true
}
```

**Response `200`:** Updated plan object.

---

### `DELETE /plans/{plan_id}` *(Admin)*

**Response `200`:** `{ "deleted": true }`  
**Errors:** `409` – active subscriptions exist on this plan.

---

### `GET /subscription`

Get the current organization's active subscription.

**Response `200`:**
```json
{
  "id":                       "uuid",
  "organizationId":           "uuid",
  "plan":                     { "id": "uuid", "name": "Starter", "slug": "starter", "priceMonthly": 29.00, "priceYearly": 290.00, "currency": "USD" },
  "status":                   "active",
  "billingCycle":             "monthly",
  "currentPeriodStart":       "2026-03-01T00:00:00Z",
  "currentPeriodEnd":         "2026-04-01T00:00:00Z",
  "trialEndsAt":              null,
  "canceledAt":               null,
  "cancellationReason":       null,
  "externalProvider":         "stripe",
  "externalSubscriptionId":   "sub_xxx",
  "createdAt":                "...",
  "updatedAt":                "..."
}
```

**Errors:** `404` – no subscription (show upgrade page).

---

### `POST /subscribe`

Subscribe to a plan.

**Request body:**
```json
{
  "planId":             "uuid",
  "billingCycle":       "monthly",
  "externalCustomerId": "cus_xxx"
}
```

`billingCycle`: `"monthly"` | `"yearly"`

**Response `201`:** Subscription object.  
**Errors:** `409` – already subscribed. `404` – plan not found.

---

### `POST /cancel`

Cancel the current subscription.

**Request body:**
```json
{
  "reason":       "Too expensive",
  "atPeriodEnd":  true
}
```

`atPeriodEnd: true` → access until period end; `false` → immediate.

**Response `200`:** Updated subscription object with `canceledAt` set.

---

### `GET /invoices`

**Query params:** `?page=1&page_size=20`

**Response `200`:**
```json
{
  "invoices": [
    {
      "id":                  "uuid",
      "organizationId":      "uuid",
      "subscriptionId":      "uuid",
      "invoiceNumber":       "INV-2026-001",
      "amount":              29.00,
      "currency":            "USD",
      "taxAmount":           0.00,
      "totalAmount":         29.00,
      "status":              "paid",
      "dueDate":             "2026-03-15T00:00:00Z",
      "paidAt":              "2026-03-10T08:00:00Z",
      "externalInvoiceId":   "in_xxx",
      "invoicePdfUrl":       "https://...",
      "billingDetails":      {},
      "createdAt":           "...",
      "updatedAt":           "..."
    }
  ],
  "pagination": { ... }
}
```

---

### `GET /invoices/{invoice_id}`

Get a single invoice.

**Response `200`:** Single invoice object.

---

### `GET /payment-methods`

**Response `200`:**
```json
{
  "paymentMethods": [
    {
      "id":                        "uuid",
      "organizationId":            "uuid",
      "type":                      "card",
      "provider":                  "stripe",
      "externalPaymentMethodId":   "pm_xxx",
      "isDefault":                 true,
      "lastFour":                  "4242",
      "cardBrand":                 "visa",
      "expiresMonth":              12,
      "expiresYear":               2028,
      "billingAddress":            {},
      "createdAt":                 "...",
      "updatedAt":                 "..."
    }
  ],
  "total": 1
}
```

---

### `POST /payment-methods`

Attach a payment method created by your Stripe/payment SDK.

**Request body:**
```json
{
  "externalPaymentMethodId": "pm_xxx",
  "type":                    "card",
  "provider":                "stripe",
  "lastFour":                "4242",
  "cardBrand":               "visa",
  "expiresMonth":            12,
  "expiresYear":             2028,
  "billingAddress":          {},
  "setAsDefault":            true
}
```

**Response `201`:** Payment method object.

---

### `PUT /payment-methods/{pm_id}/default`

Set a payment method as default.

**Response `200`:** Updated payment method object.

---

### `GET /usage`

Current-month call-minute usage.

**Response `200`:**
```json
{
  "orgId":             "uuid",
  "period":            "2026-03",
  "usedSeconds":       7320,
  "usedMinutes":       122,
  "allowedMinutes":    500,
  "remainingMinutes":  378,
  "creditBalance":     378,
  "planName":          "Starter"
}
```

`allowedMinutes: null` = unlimited plan.

---

### `GET /invoice-preview`

Estimated invoice for the current period.

**Response `200`:**
```json
{
  "orgId":      "uuid",
  "period":     "2026-03",
  "lineItems": [
    { "description": "Starter Plan", "quantity": 1, "unitPrice": 29.00, "amount": 29.00 },
    { "description": "Overage: 22 minutes @ $0.05", "quantity": 22, "unitPrice": 0.05, "amount": 1.10 }
  ],
  "subtotal":     30.10,
  "currency":     "USD",
  "estimatedAt":  "2026-03-08T10:00:00Z"
}
```

---

### `POST /webhooks/stripe`

Stripe webhook callback. **Backend-only** — do not call from frontend.

### `POST /webhooks/razorpay`

Razorpay webhook callback. **Backend-only.**

---

## 8. Feature Flags

**Prefix:** `/api/v1`

---

### `GET /features`

List all feature definitions.

**Response `200`:**
```json
{
  "features": [
    {
      "id":          "uuid",
      "key":         "ai.agents.create",
      "name":        "Create AI Agents",
      "description": "Allows creating new voice agents",
      "module":      "agents",
      "createdAt":   "...",
      "updatedAt":   "..."
    }
  ],
  "total": 24
}
```

---

### `GET /features/check?key=ai.webrtc.enabled`

Check if the current org has access to a feature.

**Response `200`:**
```json
{
  "featureKey": "ai.webrtc.enabled",
  "enabled":    true,
  "limit":      null
}
```

`limit: null` = unlimited; `limit: 0` = disabled by quota; `limit: N` = hard cap.

---

### `POST /admin/features` *(Superuser)*

**Request body:**
```json
{
  "key":         "ai.voice.custom",
  "name":        "Custom Voice",
  "description": "Upload custom TTS voice model",
  "module":      "agents"
}
```

**Response `201`:** Feature object.

---

### `POST /admin/plans/{plan_id}/features` *(Superuser)*

Assign a feature to a plan.

**Request body:**
```json
{
  "featureId":   "uuid",
  "limitValue":  null
}
```

`limitValue: null` = boolean enable; `limitValue: 5` = cap at 5.

**Response `201`:**
```json
{
  "planId":       "uuid",
  "featureId":    "uuid",
  "featureKey":   "ai.agents.create",
  "featureName":  "Create AI Agents",
  "limitValue":   null,
  "createdAt":    "..."
}
```

---

### `POST /admin/organizations/{org_id}/feature-overrides` *(Superuser)*

Grant / revoke a feature override for a specific org.

**Request body:**
```json
{
  "featureId":  "uuid",
  "enabled":    true,
  "limitValue": 50,
  "reason":     "Beta tester",
  "expiresAt":  "2026-06-01T00:00:00Z"
}
```

**Response `201`:**
```json
{
  "id":             "uuid",
  "organizationId": "uuid",
  "featureId":      "uuid",
  "featureKey":     "ai.agents.create",
  "enabled":        true,
  "limitValue":     50,
  "reason":         "Beta tester",
  "expiresAt":      "2026-06-01T00:00:00Z",
  "createdAt":      "...",
  "updatedAt":      "..."
}
```

---

### `DELETE /admin/organizations/{org_id}/feature-overrides/{override_id}` *(Superuser)*

**Response `200`:** `{ "deleted": true }`

---

## 9. Agents

**Prefix:** `/api/v1`

---

### Agent types

| `agentType` | Description |
|-------------|-------------|
| `conversational` | Free-form LLM dialogue |
| `rag_bot` | Retrieval-Augmented Generation from private docs |
| `db_bot` | Real-time database query with SQL sanitiser |
| `speaker_only` | One-way TTS broadcast (no ASR/LLM) |

### TTS voices

`af_heart` · `bf_emma` · `am_adam` · `af_sky` · `am_michael` · `bf_isabella`

---

### `POST /agents`

Create a new AI agent.

**Requires:** `agents.agent.create` permission + `ai.agents.create` feature flag.

**Request body:**
```json
{
  "name":           "Aria",
  "description":    "Customer service bot",
  "agentType":      "conversational",
  "language":       "en",
  "ttsVoice":       "af_heart",
  "systemPrompt":   "You are Aria, a helpful and friendly assistant.",
  "welcomeMessage": "Hi! How can I help you today?",
  "toolsJson":      null,
  "qdrantCollection": null,
  "metadata":       {}
}
```

**Response `201`:**
```json
{
  "id":               "uuid",
  "orgId":            "uuid",
  "name":             "Aria",
  "description":      "Customer service bot",
  "agentType":        "conversational",
  "language":         "en",
  "ttsVoice":         "af_heart",
  "welcomeMessage":   "Hi! How can I help you today?",
  "isActive":         true,
  "toolsJson":        null,
  "qdrantCollection": null,
  "metadata":         {},
  "createdAt":        "...",
  "updatedAt":        "..."
}
```

> Note: `systemPrompt` is **not** included in any list/get response. Use the dedicated `/prompt` endpoint.

**Errors:**
| Code | Meaning |
|------|---------|
| 403 `FORBIDDEN` | Missing `agents.agent.create` permission |
| 403 `FORBIDDEN` | `ai.agents.create` feature not enabled for plan |
| 422 `VALIDATION_ERROR` | Invalid `agentType` or `ttsVoice` |

---

### `GET /agents`

List all agents in the org.

**Query params:** `?page=1&page_size=20`

**Response `200`:**
```json
{
  "items": [ ...AgentResponse[] ],
  "pagination": { ... }
}
```

---

### `GET /agents/{agent_id}`

Get a single agent.

**Response `200`:** AgentResponse object.  
**Errors:** `404` – not found or belongs to different org.

---

### `PATCH /agents/{agent_id}`

Update agent fields. All fields optional.

**Request body:**
```json
{
  "name":           "Aria v2",
  "ttsVoice":       "bf_emma",
  "welcomeMessage": "Hello! How may I assist you?",
  "isActive":       true
}
```

**Response `200`:** Updated AgentResponse.

---

### `DELETE /agents/{agent_id}`

**Response `200`:** `{ "deleted": true }`

---

### `GET /agents/{agent_id}/prompt`

Get the system prompt. **This is the only endpoint that returns `systemPrompt`.**

**Requires:** `agents.agent.update` permission.

**Response `200`:**
```json
{
  "agentId":      "uuid",
  "systemPrompt": "You are Aria, a helpful and friendly assistant."
}
```

---

### `PUT /agents/{agent_id}/prompt`

Update the system prompt.

**Request body:**
```json
{
  "systemPrompt": "You are Aria v2, a professional sales assistant."
}
```

**Response `200`:**
```json
{
  "agentId":      "uuid",
  "systemPrompt": "You are Aria v2, a professional sales assistant."
}
```

---

### `POST /agents/{agent_id}/test-call`

Run a single-turn text test against the agent (no phone/WebRTC needed).

**Request body:**
```json
{
  "message": "What are your business hours?"
}
```

**Response `200`:**
```json
{
  "agentId":      "uuid",
  "input":        "What are your business hours?",
  "response":     "Our business hours are Monday to Friday, 9 AM to 6 PM.",
  "latencyMs":    234,
  "tokensUsed":   48
}
```

---

### `POST /agents/{agent_id}/webrtc/connect`

Exchange WebRTC SDP offer for an SDP answer. Starts a real-time voice session.

**Requires:** `ai.webrtc.enabled` feature flag.

**Request body:**
```json
{
  "sdp":  "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\n...",
  "type": "offer"
}
```

**Response `200`:**
```json
{
  "sdp":       "v=0\r\no=- ...",
  "type":      "answer",
  "sessionId": "sess_uuid",
  "iceServers": [
    { "urls": "stun:stun.l.google.com:19302" }
  ]
}
```

**Errors:**
| Code | Meaning |
|------|---------|
| 503 `SERVICE_UNAVAILABLE` | GPU VRAM < 1.5 GB — pipeline cannot accept new sessions |
| 403 `FORBIDDEN` | `ai.webrtc.enabled` not in plan |

See [§21 WebRTC Integration](#21-webrtc-integration) for the full browser flow.

---

### `GET /agents/{agent_id}/prompt`  ← *already documented above*

---

### Phone Number Management

#### `POST /agents/{agent_id}/phone-numbers`

Assign a Twilio-provisioned phone number to the agent.

**Request body:**
```json
{ "phoneNumber": "+15005550006" }
```

**Response `201`:**
```json
{
  "id":          "uuid",
  "agentId":     "uuid",
  "phoneNumber": "+15005550006",
  "provider":    "twilio",
  "isActive":    true,
  "createdAt":   "..."
}
```

**Errors:** `409` – number already assigned to another agent.

#### `GET /agents/{agent_id}/phone-numbers`

**Response `200`:**
```json
{
  "phoneNumbers": [ ...AgentPhoneNumberResponse[] ],
  "total": 1
}
```

---

### Knowledge Base (RAG)

Used with `agentType: "rag_bot"`.

#### `POST /agents/{agent_id}/knowledge-base`

Upload a document chunk to the agent's Qdrant vector collection.

**Requires:** `ai.rag.enabled` feature flag.

**Request body:**
```json
{
  "title":    "Refund Policy",
  "content":  "All purchases are eligible for a full refund within 30 days...",
  "metadata": { "source": "policy-doc-v3" }
}
```

**Response `201`:**
```json
{
  "id":               "uuid",
  "agentId":          "uuid",
  "title":            "Refund Policy",
  "contentSnippet":   "All purchases are eligible...",
  "qdrantPointId":    "uuid",
  "createdAt":        "..."
}
```

#### `GET /agents/{agent_id}/knowledge-base`

**Query params:** `?page=1&page_size=20`

**Response `200`:**
```json
{
  "items": [ ...KBDocResponse[] ],
  "pagination": { ... }
}
```

#### `DELETE /agents/{agent_id}/knowledge-base/{doc_id}`

Delete a single document.

**Response `200`:** `{ "deleted": true }`

#### `DELETE /agents/{agent_id}/knowledge-base`

**⚠ Destructive.** Wipes the entire knowledge base for this agent.

**Response `200`:** `{ "deleted": true, "count": 42 }`

---

### Tool Configuration

#### `PUT /agents/{agent_id}/tools`

Replace the agent's function-calling tool manifest.

**Requires:** `ai.tools.enabled` feature flag.

**Request body:**
```json
{
  "toolsJson": [
    {
      "type": "function",
      "name": "lookup_order",
      "description": "Look up an order by ID",
      "parameters": {
        "type": "object",
        "properties": {
          "order_id": { "type": "string" }
        },
        "required": ["order_id"]
      }
    }
  ]
}
```

**Response `200`:** Updated AgentResponse.

---

### `GET /agents/usage/minutes`

Usage minutes for all agents in the org.

**Response `200`:**
```json
{
  "orgId":   "uuid",
  "period":  "2026-03",
  "agents": [
    { "agentId": "uuid", "agentName": "Aria", "totalMinutes": 87 }
  ],
  "totalMinutes": 87
}
```

---

### `GET /agents/{agent_id}/calls`

List call logs for an agent.

**Query params:** `?page=1&page_size=20&status=completed`

**Response `200`:**
```json
{
  "items": [ ...CallLogResponse[] ],
  "pagination": { ... }
}
```

---

### `GET /agents/{agent_id}/analytics`

Deep-dive performance metrics for one agent.

**Query params:** `?days=7` (default: 7; max: 90)

**Response `200`:**
```json
{
  "agentId":          "uuid",
  "periodDays":       7,
  "totalCalls":       124,
  "completedCalls":   118,
  "failedCalls":      6,
  "successRate":      95.16,
  "avgDurationSec":   87.4,
  "p50SttMs":         230,
  "p95SttMs":         410,
  "p99SttMs":         680,
  "p50LlmMs":         310,
  "p95LlmMs":         590,
  "p99LlmMs":         820,
  "p50TtsMs":         180,
  "p95TtsMs":         290,
  "p99TtsMs":         440,
  "recentSamples": [
    {
      "callId":             "uuid",
      "startedAt":          "...",
      "durationSec":        92,
      "transcriptSnippet": "Hi! I need help with my order..."
    }
  ],
  "generatedAt": "..."
}
```

---

## 10. Calls & Call Logs

**Prefix:** `/api/v1`

---

### `POST /calls`

Write a completed call log. Called by the pipeline service; frontends may also use it for manual logging.

**Request body:**
```json
{
  "agentId":       "uuid",
  "orgId":         "uuid",
  "sessionId":     "sess_uuid",
  "callerId":      "+15005550001",
  "direction":     "inbound",
  "transport":     "webrtc",
  "status":        "completed",
  "startedAt":     "2026-03-08T10:00:00Z",
  "endedAt":       "2026-03-08T10:01:32Z",
  "durationSec":   92,
  "transcript":    "User: Hi! Agent: Hello, how can I help?",
  "recordingUrl":  null,
  "costCredits":   92,
  "sttMs":         245,
  "llmTtftMs":     312,
  "ttsTtfbMs":     198,
  "metadata":      {}
}
```

`direction`: `"inbound"` | `"outbound"`  
`transport`: `"webrtc"` | `"pstn"`  
`status`: `"connected"` | `"completed"` | `"failed"` | `"no-answer"`

**Response `201`:** CallLogResponse (see below).

---

### `GET /calls/{call_id}`

Get a single call log.

**Response `200`:**
```json
{
  "id":           "uuid",
  "agentId":      "uuid",
  "orgId":        "uuid",
  "sessionId":    "sess_uuid",
  "callerId":     "+15005550001",
  "direction":    "inbound",
  "transport":    "webrtc",
  "status":       "completed",
  "startedAt":    "...",
  "endedAt":      "...",
  "durationSec":  92,
  "transcript":   "User: Hi! Agent: Hello...",
  "recordingUrl": null,
  "costCredits":  92,
  "sttMs":        245,
  "llmTtftMs":    312,
  "ttsTtfbMs":    198,
  "metadata":     { "piiFlags": { "hasPii": false } },
  "createdAt":    "..."
}
```

> The `transcript` field is returned in call detail. PII detection results are in `metadata.piiFlags`.

---

### `GET /calls/{call_id}/recording`

Get a time-limited presigned URL for the call recording audio file.

**Response `200`:**
```json
{
  "url":       "https://storage.example.com/recordings/...?X-Amz-Expires=3600",
  "expiresIn": 3600
}
```

The URL is valid for **1 hour**. Stream directly from your `<audio>` element. Do not cache or expose the URL publicly.

**Errors:** `404` – no recording for this call.

---

### `POST /agents/{agent_id}/calls/outbound`

Initiate an outbound PSTN call from the agent to a phone number.

**Requires:** `ai.pstn.enabled` feature flag.

**Request body:**
```json
{
  "toNumber": "+15005550001"
}
```

**Response `201`:**
```json
{
  "callSid":   "CAxxxxxxxxxxxx",
  "sessionId": "sess_uuid",
  "from":      "+15005550006",
  "to":        "+15005550001",
  "status":    "initiated"
}
```

**Errors:**
| Code | Meaning |
|------|---------|
| 404 `NOT_FOUND` | Agent has no assigned phone number |
| 403 `FORBIDDEN` | `ai.pstn.enabled` not in plan |

---

## 11. Dashboard & Analytics

**Prefix:** `/api/v1`

---

### `GET /dashboard/overview`

Real-time snapshot for the main dashboard card.

**Response `200`:**
```json
{
  "period":              "2026-03",
  "activeCalls":         2,
  "totalCallsThisMonth": 847,
  "completedCalls":      819,
  "failedCalls":         28,
  "successRate":         96.69,
  "totalMinutesUsed":    412,
  "topAgents": [
    {
      "agentId":        "uuid",
      "agentName":      "Aria",
      "totalCalls":     512,
      "successRate":    98.4,
      "avgDurationSec": 84.2
    }
  ],
  "generatedAt": "..."
}
```

---

### `GET /dashboard/latency?window_min=60`

Latency percentiles over the last N minutes (default: 1440 = 24 h).

**Response `200`:**
```json
{
  "windowHours": 24,
  "buckets": [
    {
      "label":       "2026-03-08T09:00:00Z",
      "sampleCount": 34,
      "p50SttMs":    220,
      "p95SttMs":    380,
      "p99SttMs":    540,
      "p50LlmMs":    290,
      "p95LlmMs":    510,
      "p99LlmMs":    740,
      "p50TtsMs":    170,
      "p95TtsMs":    260,
      "p99TtsMs":    380
    }
  ],
  "summary": { "p50SttMs": 230, "p95SttMs": 400, ...  },
  "generatedAt": "..."
}
```

---

### `GET /dashboard/call-volume?period=7d`

Call volume over time. `period`: `"24h"` | `"7d"` | `"30d"` | `"90d"`

**Response `200`:**
```json
{
  "granularity": "day",
  "points": [
    {
      "label":           "2026-03-01",
      "totalCalls":      132,
      "completedCalls":  128,
      "failedCalls":     4,
      "totalDurationSec": 11520,
      "inboundCalls":    98,
      "outboundCalls":   34
    }
  ],
  "totalCalls":       924,
  "totalDurationSec": 80640,
  "generatedAt":      "..."
}
```

---

### `GET /dashboard/agent-performance`

Performance table across all agents.

**Query params:** `?days=7`

**Response `200`:**
```json
{
  "agents": [
    {
      "agentId":        "uuid",
      "agentName":      "Aria",
      "totalCalls":     512,
      "completedCalls": 502,
      "failedCalls":    10,
      "successRate":    98.05,
      "avgDurationSec": 84.2,
      "avgSttMs":       228,
      "avgLlmMs":       305,
      "avgTtsMs":       178
    }
  ],
  "periodDays":  7,
  "generatedAt": "..."
}
```

---

### `GET /agents/{agent_id}/analytics` — *see [§9 Agents](#9-agents)*

---

### `GET /admin/gpu-status`

VRAM and GPU utilization across all devices. *(Admin only)*

**Response `200`:**
```json
{
  "nvmlAvailable": true,
  "driverVersion": "535.104",
  "cudaVersion":   "12.2",
  "devices": [
    {
      "index":               0,
      "name":                "NVIDIA A10G",
      "vramTotalMib":        23028,
      "vramUsedMib":         8192,
      "vramFreeMib":         14836,
      "vramUtilizationPct":  35.6,
      "gpuUtilizationPct":   42.0,
      "temperatureCelsius":  62.0,
      "powerDrawWatts":      145.0,
      "powerLimitWatts":     300.0
    }
  ],
  "generatedAt": "..."
}
```

---

### `GET /admin/queue-status`

Celery worker and task queue health. *(Admin only)*

**Response `200`:**
```json
{
  "queues": [
    { "name": "default",      "pending": 0, "active": 2, "reserved": 0, "failed": 1 },
    { "name": "emails",       "pending": 3, "active": 0, "reserved": 0, "failed": 0 },
    { "name": "maintenance",  "pending": 0, "active": 0, "reserved": 0, "failed": 0 }
  ],
  "workersOnline": 2,
  "generatedAt":   "..."
}
```

---

### `POST /admin/model-benchmark`

Run a latency benchmark on a pipeline model. *(Admin only)*

**Request body:**
```json
{
  "modelName":  "whisper-large-v3",
  "sampleText": "The quick brown fox jumps over the lazy dog.",
  "runs":        3
}
```

**Response `200`:**
```json
{
  "results": [
    {
      "modelName":    "whisper-large-v3",
      "runs":          3,
      "avgLatencyMs":  230.4,
      "p50LatencyMs":  224.0,
      "p95LatencyMs":  257.0,
      "minLatencyMs":  218.0,
      "maxLatencyMs":  261.0,
      "error":         null
    }
  ],
  "benchmarkAt": "..."
}
```

---

## 12. Notifications

**Prefix:** `/api/v1`

---

### `GET /notifications`

List notifications for the current user.

**Query params:** `?page=1&page_size=20&is_read=false`

**Response `200`:**
```json
{
  "notifications": [
    {
      "id":             "uuid",
      "userId":         "uuid",
      "organizationId": "uuid",
      "type":           "call.completed",
      "channel":        "in_app",
      "title":          "Call completed",
      "body":           "Aria completed a 92-second call",
      "data":           { "callId": "uuid", "agentId": "uuid" },
      "isRead":         false,
      "readAt":         null,
      "createdAt":      "..."
    }
  ],
  "pagination": { ... }
}
```

---

### `GET /notifications/count`

**Response `200`:**
```json
{ "unreadCount": 7 }
```

---

### `GET /notifications/stream`

**Server-Sent Events** stream for real-time notifications.

See [§19 SSE Streams](#19-real-time-sse-streams) for connection details.

---

### `PUT /notifications/read-all`

Mark all notifications as read.

**Response `200`:**
```json
{ "markedCount": 7 }
```

---

### `PUT /notifications/{notification_id}/read`

Mark a single notification as read.

**Response `200`:**
```json
{
  "notification": { ...NotificationResponse with isRead: true }
}
```

---

### `GET /notifications/preferences`

Get notification preference settings for the current user.

**Response `200`:**
```json
{
  "preferences": [
    {
      "id":               "uuid",
      "userId":           "uuid",
      "notificationType": "call.completed",
      "channel":          "email",
      "isEnabled":        true
    },
    {
      "id":               "uuid",
      "userId":           "uuid",
      "notificationType": "call.failed",
      "channel":          "in_app",
      "isEnabled":        true
    }
  ]
}
```

---

### `PUT /notifications/preferences`

Bulk-update preferences.

**Request body:**
```json
{
  "preferences": [
    { "notificationType": "call.completed", "channel": "email",  "isEnabled": false },
    { "notificationType": "call.failed",    "channel": "in_app", "isEnabled": true  }
  ]
}
```

**Response `200`:**
```json
{ "preferences": [ ...updated list ] }
```

---

### `POST /notifications/test-send`

Send a test notification to yourself (for testing UI).

**Request body:**
```json
{
  "channel": "in_app",
  "message": "This is a test notification"
}
```

**Response `200`:** `{ "sent": true }`

---

## 13. Files

**Prefix:** `/api/v1/files`

---

### `POST /upload`

Upload a file. **`multipart/form-data`** — do not send `Content-Type: application/json`.

**Form field:** `file` (binary)

```html
<input type="file" id="upload" />
<script>
  const form = new FormData();
  form.append('file', document.getElementById('upload').files[0]);

  fetch('/api/v1/files/upload', {
    method:  'POST',
    headers: { 'Authorization': `Bearer ${token}`, 'X-Org-ID': orgId },
    body:    form,
  });
</script>
```

**Response `201`:**
```json
{
  "file": {
    "id":              "uuid",
    "organizationId":  "uuid",
    "uploadedBy":      "uuid",
    "fileName":        "a1b2c3d4.pdf",
    "originalName":    "refund-policy.pdf",
    "mimeType":        "application/pdf",
    "fileSizeBytes":   204800,
    "storageProvider": "s3",
    "storagePath":     "orgs/uuid/2026/03/a1b2c3d4.pdf",
    "attachableType":  null,
    "attachableId":    null,
    "checksum":        "sha256:abc...",
    "isPublic":        false,
    "metadata":        {},
    "createdAt":       "...",
    "updatedAt":       "..."
  },
  "deduplicated": false
}
```

`deduplicated: true` means an identical file already existed — no new storage consumed.

---

### `GET /`

List uploaded files for the current org.

**Query params:** `?page=1&page_size=20`

**Response `200`:**
```json
{
  "files": [ ...FileResponse[] ],
  "pagination": { ... }
}
```

---

### `GET /{file_id}`

Get file metadata.

**Response `200`:** FileResponse object.

---

### `GET /{file_id}/download`

Get a presigned download URL (1-hour TTL).

**Response `200`:**
```json
{
  "url":       "https://s3.amazonaws.com/bucket/...",
  "expiresIn": 3600
}
```

---

### `DELETE /{file_id}`

Delete a file.

**Response `200`:**
```json
{
  "deleted": true,
  "fileId":  "uuid"
}
```

---

## 14. API Keys

**Prefix:** `/api/v1`

---

### `POST /api-keys`

Create an API key for programmatic access.

**Request body:**
```json
{
  "name":               "CI Pipeline",
  "scopes":             ["agents:read", "calls:read"],
  "rateLimitPerMinute": 120,
  "expiresAt":          "2027-01-01T00:00:00Z"
}
```

**Response `201`:**
```json
{
  "id":       "uuid",
  "key":      "vsk_live_XXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
  "prefix":   "vsk_live_XX",
  "name":     "CI Pipeline",
  "scopes":   ["agents:read", "calls:read"],
  "createdAt": "..."
}
```

> ⚠ `key` is **returned only once** at creation. Store it securely.

---

### `GET /api-keys`

List API keys (without the secret value).

**Response `200`:**
```json
{
  "apiKeys": [
    {
      "id":                 "uuid",
      "prefix":             "vsk_live_XX",
      "name":               "CI Pipeline",
      "scopes":             ["agents:read"],
      "rateLimitPerMinute": 120,
      "lastUsedAt":         "...",
      "expiresAt":          "2027-01-01T00:00:00Z",
      "isActive":           true,
      "createdAt":          "..."
    }
  ],
  "total": 1
}
```

---

### `DELETE /api-keys/{key_id}`

Revoke an API key.

**Response `200`:** `{ "revoked": true }`

---

### `GET /api-keys/verify`

Verify the API key in the `Authorization: ApiKey <key>` header.

**Response `200`:**
```json
{
  "valid":  true,
  "keyId":  "uuid",
  "scopes": ["agents:read"]
}
```

---

## 15. Webhooks

**Prefix:** `/api/v1`

Outbound webhooks — the platform POSTs to your URL for registered events.

---

### `POST /webhooks`

Register a webhook endpoint.

**Request body:**
```json
{
  "url":    "https://yourapp.com/hooks/voicesaas",
  "events": ["call.completed", "call.failed", "agent.updated"],
  "secret": "your_signing_secret"
}
```

**Available events:** `call.started` · `call.completed` · `call.failed` · `agent.created` · `agent.updated` · `agent.deleted` · `subscription.activated` · `subscription.canceled` · `invoice.paid`

**Response `201`:**
```json
{
  "id":         "uuid",
  "url":        "https://yourapp.com/hooks/voicesaas",
  "events":     ["call.completed", "call.failed"],
  "isActive":   true,
  "createdAt":  "..."
}
```

---

### `GET /webhooks`

**Response `200`:**
```json
{
  "webhooks": [ ...WebhookResponse[] ],
  "pagination": { ... }
}
```

---

### `GET /webhooks/{webhook_id}`

Get a single webhook.

---

### `PATCH /webhooks/{webhook_id}`

**Request body:**
```json
{
  "events":   ["call.completed"],
  "isActive": true
}
```

**Response `200`:** Updated webhook object.

---

### `DELETE /webhooks/{webhook_id}`

**Response `200`:** `{ "deleted": true }`

---

### `GET /webhooks/{webhook_id}/deliveries`

List delivery attempts with status and response codes.

**Response `200`:**
```json
{
  "deliveries": [
    {
      "id":           "uuid",
      "webhookId":    "uuid",
      "event":        "call.completed",
      "statusCode":   200,
      "success":      true,
      "requestBody":  "{...}",
      "responseBody": "ok",
      "attempt":      1,
      "createdAt":    "..."
    }
  ],
  "pagination": { ... }
}
```

---

### Webhook payload format

All outbound webhook POST bodies follow this envelope:

```json
{
  "event":   "call.completed",
  "orgId":   "uuid",
  "data":    { ...event-specific payload },
  "sentAt":  "2026-03-08T10:01:32Z"
}
```

Verify the signature using the `X-VoiceSaaS-Signature` header (HMAC-SHA256 of the raw body with your `secret`):

```js
const crypto = require('crypto');

function verifyWebhook(rawBody, signature, secret) {
  const expected = crypto
    .createHmac('sha256', secret)
    .update(rawBody)
    .digest('hex');
  return `sha256=${expected}` === signature;
}
```

---

## 16. Audit Logs

**Prefix:** `/api/v1`

---

### `GET /audit/logs`

**Query params:** `?page=1&page_size=20&action=agent.call.completed&from=2026-03-01&to=2026-03-08`

**Response `200`:**
```json
{
  "logs": [
    {
      "id":           "uuid",
      "orgId":        "uuid",
      "actorId":      "uuid",
      "action":       "agent.call.completed",
      "resourceType": "agent",
      "resourceId":   "uuid",
      "ipAddress":    "1.2.3.4",
      "userAgent":    "Mozilla/5.0 ...",
      "metadata":     { "callId": "uuid", "durationSec": 92 },
      "createdAt":    "..."
    }
  ],
  "pagination": { ... }
}
```

---

### `GET /audit/logs/export`

Export audit logs as CSV. Streams the file directly.

**Query params:** `?from=2026-03-01&to=2026-03-08`

**Response:** `text/csv` file download.

---

### `GET /audit/logs/{log_id}`

Get a single audit log entry.

**Response `200`:** Single audit log object.

---

## 17. Security

**Prefix:** `/api/v1`

---

### `GET /security/login-attempts`

**Query params:** `?page=1&page_size=20&email=alice@example.com`

**Response `200`:**
```json
{
  "attempts": [
    {
      "id":             "uuid",
      "userId":         "uuid",
      "email":          "alice@example.com",
      "ipAddress":      "1.2.3.4",
      "userAgent":      "Mozilla/5.0 ...",
      "method":         "password",
      "isSuccess":      false,
      "failureReason":  "wrong_password",
      "attemptedAt":    "..."
    }
  ],
  "pagination": { ... }
}
```

---

### `GET /security/blocked-ips`

**Response `200`:**
```json
{
  "blockedIps": [
    {
      "id":           "uuid",
      "ipAddress":    "1.2.3.4",
      "reason":       "Brute force",
      "blockedBy":    "uuid",
      "blockedUntil": "2026-03-09T10:00:00Z",
      "isActive":     true,
      "createdAt":    "..."
    }
  ],
  "pagination": { ... }
}
```

---

### `POST /security/blocked-ips`

Block an IP address.

**Request body:**
```json
{
  "ipAddress": "1.2.3.4",
  "reason":    "Attempted brute force",
  "hours":     48
}
```

`hours: null` = permanent block.

**Response `201`:** BlockedIPResponse object.

---

### `DELETE /security/blocked-ips/{blocked_id}`

Unblock an IP.

**Response `200`:** `{ "unblocked": true }`

---

### `GET /security/events`

Suspicious activity events (IPs with repeated failures).

**Response `200`:**
```json
{
  "events": [
    {
      "ipAddress":       "8.8.4.4",
      "failureCount":    47,
      "firstSeen":       "...",
      "lastSeen":        "...",
      "isBlocked":       true,
      "emailsTargeted":  ["alice@example.com", "admin@demo.local"]
    }
  ]
}
```

---

## 18. System

**Prefix:** `/api/v1`

---

### `GET /health`

Simple health probe. **No auth, no prefix.**

```
GET http://localhost:8000/health
```

**Response `200`:**
```json
{
  "status":    "ok",
  "version":   "1.0.0",
  "timestamp": "2026-03-08T10:00:00Z"
}
```

---

### `GET /system/health`

Detailed health with component probes.

**Response `200`:**
```json
{
  "status":      "healthy",
  "version":     "1.0.0",
  "environment": "production",
  "timestamp":   "...",
  "components": {
    "database": { "status": "ok",       "latencyMs": 2.4  },
    "redis":    { "status": "ok",       "latencyMs": 0.8  },
    "qdrant":   { "status": "degraded", "latencyMs": null, "detail": "timeout" }
  },
  "disk": {
    "totalGb":   100.0,
    "usedGb":    34.2,
    "freeGb":    65.8,
    "percentUsed": 34.2
  }
}
```

`status`: `"healthy"` | `"degraded"` | `"unhealthy"`

---

### `GET /system/metrics`

Prometheus-format metrics. Consumed by Grafana — not for direct frontend use.

---

### `GET /system/settings` *(Admin)*

List all system settings.

**Response `200`:**
```json
{
  "settings": [
    {
      "id":          "uuid",
      "key":         "maintenance.mode",
      "value":       false,
      "description": "Enable maintenance mode",
      "isPublic":    true,
      "updatedBy":   "uuid",
      "updatedAt":   "..."
    }
  ],
  "count": 12
}
```

---

### `GET /system/settings/{key}`

**Response `200`:** Single setting object.

---

### `PUT /system/settings/{key}` *(Admin)*

**Request body:**
```json
{
  "value":       true,
  "description": "Enabled for scheduled maintenance"
}
```

**Response `200`:** Updated setting object.

---

### `DELETE /system/settings/{key}` *(Admin)*

**Response `200`:** `{ "deleted": true }`

---

### `GET /admin/stats` *(Superuser)*

Platform-wide statistics.

**Response `200`:**
```json
{
  "totalUsers":           12480,
  "activeUsers":          9340,
  "totalOrganizations":   1820,
  "activeOrganizations":  1640,
  "totalFiles":           54920,
  "totalFileSizeBytes":   18234567890,
  "activeSubscriptions":  1420,
  "mrrUsd":               58180.00,
  "arrUsd":               698160.00,
  "periodNewUsers30d":    340,
  "periodNewOrgs30d":     82
}
```

---

## 19. Real-Time: SSE Streams

The platform exposes two **Server-Sent Events** streams.

### Connection

```js
const token  = getAccessToken();
const orgId  = getCurrentOrgId();

const es = new EventSource(
  `/api/v1/notifications/stream?token=${token}&org_id=${orgId}`
);
```

> Some browsers block `EventSource` with custom headers. Pass credentials as query params or use a polyfill. Alternatively, use `fetch` with `ReadableStream`.

---

### Notification Stream — `GET /api/v1/notifications/stream`

Sends new in-app notifications in real time.

**Event format:**
```
event: notification
data: {"id":"uuid","type":"call.completed","title":"Call completed","body":"Aria completed a 92s call","data":{"callId":"uuid"},"isRead":false,"createdAt":"..."}
```

```js
es.addEventListener('notification', (e) => {
  const n = JSON.parse(e.data);
  showToast(n.title, n.body);
  incrementUnreadBadge();
});

es.addEventListener('error', () => {
  // Reconnect after 5s
  setTimeout(() => reconnect(), 5000);
});
```

---

### Live Calls Stream — `GET /api/v1/calls/live`

Streams live call start/end/fail events for the org dashboard.

**Event types:**

#### `call.started`
```
event: call.started
data: {"callId":"uuid","agentId":"uuid","agentName":"Aria","direction":"inbound","transport":"webrtc","startedAt":"..."}
```

#### `call.ended`
```
event: call.ended
data: {"callId":"uuid","agentId":"uuid","durationSec":92,"recordingUrl":null}
```

#### `call.failed`
```
event: call.failed
data: {"callId":"uuid","agentId":"uuid","reason":"no-answer"}
```

```js
const es = new EventSource(
  `/api/v1/calls/live?token=${token}&org_id=${orgId}`
);

es.addEventListener('call.started', (e) => {
  const ev = JSON.parse(e.data);
  addToActiveCalls(ev);
});

es.addEventListener('call.ended', (e) => {
  const ev = JSON.parse(e.data);
  removeFromActiveCalls(ev.callId);
  updateCallStats();
});
```

---

### Reconnection

Both streams send a `keep-alive` comment every 15 seconds:

```
: keep-alive
```

Implement exponential back-off reconnection:

```js
let retryDelay = 1000;

function connect() {
  const es = new EventSource(url);
  es.onopen = () => { retryDelay = 1000; };
  es.onerror = () => {
    es.close();
    setTimeout(connect, Math.min(retryDelay *= 2, 30000));
  };
}
```

---

## 20. Twilio Webhook Callbacks

These endpoints are called directly by Twilio — **do not call them from your frontend**. They are documented here so you understand the flow and can test it.

---

### `POST /api/v1/webhooks/twilio/inbound/{phone_number}`

Called by Twilio when someone dials a VoiceSaaS-managed number.

**Validation:** Every request must have a valid `X-Twilio-Signature` HMAC header. Requests without a valid signature return **HTTP 401**.

**Body (Twilio form-encoded):**
```
AccountSid=ACxxxxx&CallSid=CAxxxxx&From=%2B15005550001&To=%2B15005550006&CallStatus=ringing
```

**Response:** TwiML XML (`application/xml`):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://pipeline.yourdomain.com/ws/CAxxxxx" />
  </Connect>
</Response>
```

---

### `POST /api/v1/webhooks/twilio/connect/{session_id}`

Called by Twilio when an outbound call is answered. Returns the same `<Connect><Stream>` TwiML.

---

## 21. WebRTC Integration

Full browser-to-agent voice session using the JavaScript SDK.

### Install SDK

```bash
npm install ./sdk   # local SDK (sdk/ai-call-sdk.js in this repo)
# or after publishing:
npm install @voicesaas/call-sdk
```

---

### Quick start

```js
import { VoiceSession } from '@voicesaas/call-sdk';

const session = new VoiceSession({
  apiBase: 'http://localhost:8000/api/v1',
  token:    getAccessToken(),
  orgId:    getCurrentOrgId(),
});

// Start a call with agent
await session.connect({ agentId: 'uuid' });

// Session events
session.on('connected',    ()  => console.log('Call connected'));
session.on('transcript',   (t) => console.log('Transcript:', t.text));
session.on('disconnected', ()  => console.log('Call ended'));
session.on('error',        (e) => console.error('Error:', e));

// End the call
await session.disconnect();
```

---

### Manual SDP flow (without SDK)

```js
// 1. Create PeerConnection
const pc = new RTCPeerConnection({
  iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
});

// 2. Add microphone track
const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
stream.getTracks().forEach(t => pc.addTrack(t, stream));

// 3. Create SDP offer
const offer = await pc.createOffer();
await pc.setLocalDescription(offer);

// 4. POST offer to API
const res  = await apiFetch(`/agents/${agentId}/webrtc/connect`, {
  method: 'POST',
  body:   JSON.stringify({ sdp: offer.sdp, type: offer.type }),
});
const answer = await res.json();

// 5. Set answer
await pc.setRemoteDescription({ type: answer.type, sdp: answer.sdp });

// 6. Play incoming audio
pc.ontrack = (e) => {
  const audio = document.createElement('audio');
  audio.srcObject = e.streams[0];
  audio.autoplay = true;
  document.body.appendChild(audio);
};
```

### Error handling for WebRTC

| HTTP status | `code` | Action |
|-------------|--------|--------|
| 503 | `SERVICE_UNAVAILABLE` | Show "Server busy" — retry after 10s |
| 403 | `FORBIDDEN` | Show upgrade prompt — plan doesn't include WebRTC |
| 404 | `NOT_FOUND` | Agent doesn't exist |
| 422 | `VALIDATION_ERROR` | SDP offer malformed |

---

## 22. SDK Reference

The JavaScript SDK is at `sdk/ai-call-sdk.js`.

### `VoiceSession`

```ts
new VoiceSession(config: {
  apiBase: string;      // e.g. "http://localhost:8000/api/v1"
  token:   string;      // Bearer access token
  orgId:   string;      // X-Org-ID header value
})
```

#### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `connect({ agentId })` | `Promise<void>` | Initiate WebRTC session |
| `disconnect()` | `Promise<void>` | End session gracefully |
| `mute()` | `void` | Mute local microphone |
| `unmute()` | `void` | Unmute |

#### Events

| Event | Data | Description |
|-------|------|-------------|
| `connected` | `{ sessionId }` | Session established |
| `disconnected` | `{ durationMs }` | Session ended |
| `transcript` | `{ text, isFinal, speaker }` | Partial/final transcript segment |
| `error` | `Error` | Connection or media error |

---

## Quick Reference Card

### All endpoints at a glance

```
POST   /api/v1/auth/register              POST   /api/v1/agents
POST   /api/v1/auth/login                 GET    /api/v1/agents
POST   /api/v1/auth/refresh               GET    /api/v1/agents/{id}
POST   /api/v1/auth/logout                PATCH  /api/v1/agents/{id}
GET    /api/v1/auth/me                    DELETE /api/v1/agents/{id}
POST   /api/v1/auth/2fa/setup             GET    /api/v1/agents/{id}/prompt
POST   /api/v1/auth/2fa/verify            PUT    /api/v1/agents/{id}/prompt
                                          POST   /api/v1/agents/{id}/test-call
POST   /api/v1/organizations              POST   /api/v1/agents/{id}/webrtc/connect
GET    /api/v1/organizations/{slug}       POST   /api/v1/agents/{id}/phone-numbers
PATCH  /api/v1/organizations/{id}         GET    /api/v1/agents/{id}/phone-numbers
GET    /api/v1/organizations/{id}/members POST   /api/v1/agents/{id}/knowledge-base
POST   /api/v1/organizations/{id}/invit.  GET    /api/v1/agents/{id}/knowledge-base
POST   /api/v1/invitations/accept         DELETE /api/v1/agents/{id}/knowledge-base
                                          PUT    /api/v1/agents/{id}/tools
GET    /api/v1/billing/plans              GET    /api/v1/agents/{id}/calls
POST   /api/v1/billing/subscribe          GET    /api/v1/agents/{id}/analytics
GET    /api/v1/billing/subscription       POST   /api/v1/agents/{id}/calls/outbound
GET    /api/v1/billing/invoices
GET    /api/v1/billing/usage              POST   /api/v1/calls
GET    /api/v1/billing/invoice-preview    GET    /api/v1/calls/{id}
                                          GET    /api/v1/calls/{id}/recording
GET    /api/v1/rbac/roles
POST   /api/v1/rbac/roles                 GET    /api/v1/dashboard/overview
GET    /api/v1/rbac/permissions           GET    /api/v1/dashboard/latency
                                          GET    /api/v1/dashboard/call-volume
GET    /api/v1/notifications              GET    /api/v1/dashboard/agent-performance
GET    /api/v1/notifications/count        GET    /api/v1/calls/live         ← SSE
GET    /api/v1/notifications/stream  ← SSE

GET    /api/v1/audit/logs                 GET    /api/v1/system/health
GET    /api/v1/audit/logs/export          GET    /health
GET    /api/v1/security/events            GET    /docs
```

---

*Last updated: 2026-03-08 — 135 endpoints across 15 modules*
