import { useCallback, useRef, useState } from 'react';

// Controlled dialogs can have several launch buttons. Remember the actual one
// so keyboard users return to their place when a dialog closes.
export function useDialogState() {
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const onOpenChange = useCallback((next: boolean) => {
    if (next && document.activeElement instanceof HTMLElement) {
      opener.current = document.activeElement;
    }
    setOpen(next);
  }, []);
  const restoreFocus = useCallback((event: Event) => {
    event.preventDefault();
    opener.current?.focus();
  }, []);
  return { open, onOpenChange, restoreFocus };
}
