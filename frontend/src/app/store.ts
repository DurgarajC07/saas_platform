/**
 * Root Zustand store — combines all feature slices.
 *
 * Convention: domain-local state (auth, UI preferences) lives in feature stores.
 * Only truly global, cross-cutting state should go here.
 */
import { create } from 'zustand'

interface RootState {
  /** Sidebar collapsed state */
  sidebarCollapsed: boolean
  toggleSidebar: () => void

  /** Global loading overlay (for route transitions, etc.) */
  isGlobalLoading: boolean
  setGlobalLoading: (v: boolean) => void
}

export const useRootStore = create<RootState>((set) => ({
  sidebarCollapsed: false,
  toggleSidebar:    () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),

  isGlobalLoading: false,
  setGlobalLoading: (v) => set({ isGlobalLoading: v }),
}))
