import { create } from 'zustand'

interface ScannerStore {
  /** Active profile filter — null means "All" */
  activeProfile: string | null
  /** True while a scan is running in the background */
  isScanning: boolean
  /** Wall-clock time when the last scan was triggered */
  scanStartTime: Date | null
  /** Wall-clock time when results were last fetched successfully */
  lastFetched: Date | null

  setActiveProfile: (profile: string | null) => void
  setIsScanning: (scanning: boolean) => void
  setScanStartTime: (t: Date | null) => void
  setLastFetched: (t: Date | null) => void
}

export const useScannerStore = create<ScannerStore>((set) => ({
  activeProfile: null,
  isScanning: false,
  scanStartTime: null,
  lastFetched: null,

  setActiveProfile: (profile) => set({ activeProfile: profile }),
  setIsScanning: (scanning) => set({ isScanning: scanning }),
  setScanStartTime: (t) => set({ scanStartTime: t }),
  setLastFetched: (t) => set({ lastFetched: t }),
}))
