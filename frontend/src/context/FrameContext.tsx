import { createContext, useContext } from "react";
import type { FrameSnapshot } from "../types";

export interface FrameContextValue {
  frame: FrameSnapshot | null;
  connected: boolean;
  error: string | null;
}

export const FrameContext = createContext<FrameContextValue>({
  frame: null,
  connected: false,
  error: null,
});

export function useFrameContext() {
  return useContext(FrameContext);
}
