declare module 'framer-motion' {
  import * as React from 'react';

  export interface AnimatePresenceProps {
    children?: React.ReactNode;
    mode?: 'sync' | 'wait' | 'popLayout';
    initial?: boolean;
    onExitComplete?: () => void;
    exitBeforeEnter?: boolean;
    custom?: any;
    presenceAffectsLayout?: boolean;
  }

  export const AnimatePresence: React.FC<AnimatePresenceProps>;
  export const motion: any;
  export const LazyMotion: any;
  export const domAnimation: any;
  export const m: any;
  export const useAnimation: any;
  export const useMotionValue: any;
  export const useTransform: any;
  export const useSpring: any;
  export const useScroll: any;
  export const useInView: any;
  export const AnimationControls: any;
}
