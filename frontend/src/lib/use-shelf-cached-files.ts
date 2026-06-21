import { useEffect, useState } from "react";

import { fetchShelfCachedFiles } from "@/lib/api";

export type ShelfCachedState = {
  files: { format: string; path: string }[];
  ready: boolean;
};

export function useShelfCachedFiles(
  itemId: number,
  updatedAt?: string | null
): ShelfCachedState & { hasLocalFile: boolean; primaryPath: string | null; primaryFormat: string | null } {
  const [state, setState] = useState<ShelfCachedState>({ files: [], ready: false });

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, ready: false }));
    void fetchShelfCachedFiles(itemId)
      .then((resp) => {
        if (!cancelled) {
          setState({ files: resp.files, ready: true });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({ files: [], ready: true });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [itemId, updatedAt]);

  const primary = state.files[0];
  return {
    ...state,
    hasLocalFile: state.files.length > 0,
    primaryPath: primary?.path ?? null,
    primaryFormat: primary?.format ?? null
  };
}

export async function probeShelfCachedFiles(itemId: number): Promise<ShelfCachedState> {
  try {
    const resp = await fetchShelfCachedFiles(itemId);
    return { files: resp.files, ready: true };
  } catch {
    return { files: [], ready: true };
  }
}
