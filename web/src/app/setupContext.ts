import { createContext, useContext } from "react";

/** needed = no provider is connected yet (first run, or the user is trying test mode). */
export const SetupContext = createContext<{ needed: boolean }>({ needed: false });
export const useSetupNeeded = () => useContext(SetupContext).needed;
