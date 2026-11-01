// Same-origin WebSocket URL. In dev the Vite proxy forwards /ws -> :8000;
// in prod the SPA is served from the backend so location.host already matches.
export const wsUrl = (path: string): string =>
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;
