import { create } from 'zustand';
import type { BacktestResponse, SweepResponse, StrategyType } from '../types';

interface BacktestStore {
  // Form state
  strategyType: StrategyType;
  symbol: string;
  timeframe: 'Daily' | 'Weekly';
  startDate: string;
  endDate: string;
  initialCapital: number;
  parameters: Record<string, unknown>;

  // Results state
  result: BacktestResponse | null;
  sweepResult: SweepResponse | null;
  selectedSweepIndex: number | null;
  isRunning: boolean;
  isSweeping: boolean;
  error: string | null;

  // Setters
  setStrategyType: (strategy: StrategyType) => void;
  setSymbol: (symbol: string) => void;
  setTimeframe: (timeframe: 'Daily' | 'Weekly') => void;
  setStartDate: (date: string) => void;
  setEndDate: (date: string) => void;
  setInitialCapital: (capital: number) => void;
  setParameters: (params: Record<string, unknown>) => void;
  setParameter: (key: string, value: unknown) => void;

  setResult: (result: BacktestResponse | null) => void;
  setSweepResult: (result: SweepResponse | null) => void;
  setSelectedSweepIndex: (index: number | null) => void;
  setIsRunning: (running: boolean) => void;
  setIsSweeping: (sweeping: boolean) => void;
  setError: (error: string | null) => void;

  reset: () => void;
}

const initialState = {
  strategyType: 'ema_crossover' as StrategyType,
  symbol: '',
  timeframe: 'Daily' as const,
  startDate: '',
  endDate: '',
  initialCapital: 10000,
  parameters: {},
  result: null,
  sweepResult: null,
  selectedSweepIndex: null,
  isRunning: false,
  isSweeping: false,
  error: null,
};

export const useBacktestStore = create<BacktestStore>((set) => ({
  ...initialState,

  setStrategyType: (strategy) => set({ strategyType: strategy, parameters: {} }),
  setSymbol: (symbol) => set({ symbol }),
  setTimeframe: (timeframe) => set({ timeframe }),
  setStartDate: (date) => set({ startDate: date }),
  setEndDate: (date) => set({ endDate: date }),
  setInitialCapital: (capital) => set({ initialCapital: capital }),
  setParameters: (params) => set({ parameters: params }),
  setParameter: (key, value) =>
    set((state) => ({
      parameters: { ...state.parameters, [key]: value },
    })),

  setResult: (result) => set({ result }),
  setSweepResult: (result) => set({ sweepResult: result }),
  setSelectedSweepIndex: (index) => set({ selectedSweepIndex: index }),
  setIsRunning: (running) => set({ isRunning: running }),
  setIsSweeping: (sweeping) => set({ isSweeping: sweeping }),
  setError: (error) => set({ error }),

  reset: () => set(initialState),
}));
