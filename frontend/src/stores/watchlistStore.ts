import { create } from 'zustand';

interface WatchlistUIStore {
  selectedWatchlistId: number | null;
  setSelectedWatchlistId: (id: number | null) => void;
}

export const useWatchlistStore = create<WatchlistUIStore>((set) => ({
  selectedWatchlistId: null,
  setSelectedWatchlistId: (id) => set({ selectedWatchlistId: id }),
}));
