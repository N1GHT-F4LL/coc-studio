import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { wsUrl } from "../api/ws";

// A frame callback gets the latest decoded device screen. Subscribers draw it
// however they like (DeviceView/BattleCanvas/DevicePanel). The bitmap is owned
// by the provider and reused/closed between frames — draw synchronously inside
// the callback; do not retain it.
type FrameCb = (bmp: ImageBitmap) => void;

interface DeviceStreamCtx {
  connected: boolean;
  goToDevice: () => void;
  /** Subscribe to device frames. Returns an unsubscribe fn. While ≥1 subscriber
   *  is active AND the device is connected, the provider keeps exactly one WS
   *  open to /ws/device. */
  subscribe: (cb: FrameCb) => () => void;
}

const Ctx = createContext<DeviceStreamCtx>({
  connected: false,
  goToDevice: () => {},
  subscribe: () => () => {},
});

export function DeviceStreamProvider({
  connected,
  onGotoDevice,
  children,
}: {
  connected: boolean;
  onGotoDevice: () => void;
  children: ReactNode;
}) {
  const subsRef = useRef<Set<FrameCb>>(new Set());
  const wsRef = useRef<WebSocket | null>(null);
  const [subCount, setSubCount] = useState(0);

  const subscribe = useCallback((cb: FrameCb) => {
    subsRef.current.add(cb);
    setSubCount(subsRef.current.size);
    return () => {
      subsRef.current.delete(cb);
      setSubCount(subsRef.current.size);
    };
  }, []);

  // Open exactly one WS while there are subscribers and the device is connected.
  // Depend only on the boolean `want` (not subCount itself) so adding/removing a
  // subscriber doesn't tear down and re-open the socket — that churn was opening
  // multiple overlapping streams.
  const want = connected && subCount > 0;
  useEffect(() => {
    if (!want) return; // no subscribers or not connected — stay closed
    const ws = new WebSocket(wsUrl("/ws/device?fps=4"));
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    ws.onmessage = async (e) => {
      if (typeof e.data === "string") return; // {type:"no_frame"} — ignore
      const bmp = await createImageBitmap(new Blob([e.data], { type: "image/jpeg" }));
      for (const cb of subsRef.current) {
        try {
          cb(bmp);
        } catch {
          /* a bad subscriber shouldn't kill the stream */
        }
      }
      bmp.close();
    };
    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null;
    };
    return () => {
      ws.close();
      if (wsRef.current === ws) wsRef.current = null;
    };
  }, [want]);

  return (
    <Ctx.Provider value={{ connected, goToDevice: onGotoDevice, subscribe }}>
      {children}
    </Ctx.Provider>
  );
}

export function useDeviceStream() {
  return useContext(Ctx);
}

// Convenience: subscribe to frames for the lifetime of a component.
export function useDeviceFrames(onFrame: FrameCb) {
  const { subscribe } = useDeviceStream();
  const cbRef = useRef(onFrame);
  cbRef.current = onFrame;
  useEffect(() => subscribe((bmp) => cbRef.current(bmp)), [subscribe]);
}
