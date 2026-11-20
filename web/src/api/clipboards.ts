import apiClient from './client'
import type { ClipboardItem, ClipboardListResponse, ClipboardKind } from '@/types'

export interface ClipboardListParams {
  page?: number
  page_size?: number
  kind?: ClipboardKind
  q?: string
}

export interface ClipboardCreatePayload {
  kind?: ClipboardKind
  title?: string | null
  language?: string | null
  content: string
}

export interface ClipboardUpdatePayload {
  kind?: ClipboardKind
  title?: string | null
  language?: string | null
  content?: string
}

export interface ClipboardLimits {
  max_content_len: number
  max_items: number
  max_code_items: number
}

export const clipboardsApi = {
  async list(params: ClipboardListParams = {}): Promise<ClipboardListResponse> {
    return apiClient.get('/api/clipboards', { params })
  },

  async getLimits(): Promise<ClipboardLimits> {
    return apiClient.get('/api/clipboards/limits')
  },

  async get(id: number): Promise<ClipboardItem> {
    return apiClient.get(`/api/clipboards/${id}`)
  },

  async create(payload: ClipboardCreatePayload): Promise<ClipboardItem> {
    return apiClient.post('/api/clipboards', payload)
  },

  async update(id: number, payload: ClipboardUpdatePayload): Promise<ClipboardItem> {
    return apiClient.patch(`/api/clipboards/${id}`, payload)
  },

  async remove(id: number): Promise<{ success: boolean }> {
    return apiClient.delete(`/api/clipboards/${id}`)
  },
}
