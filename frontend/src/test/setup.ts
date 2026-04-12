import '@testing-library/jest-dom';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';
import { server } from './mocks/server';

declare global {
  // eslint-disable-next-line no-var
  var ResizeObserver: typeof ResizeObserver;
}

// ResizeObserver polyfill for tests
globalThis.ResizeObserver = class {
  observe = vi.fn();
  disconnect = vi.fn();
} as unknown as typeof ResizeObserver;

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
