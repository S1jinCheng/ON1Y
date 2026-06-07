/** Shared frosted-glass nav / filter selection (see globals.css `.on1y-glass-*`). */

export const GLASS_SELECTED = "on1y-glass-selected";
export const GLASS_IDLE = "on1y-glass-idle";
export const GLASS_PANEL = "on1y-glass-panel";
export const GLASS_MUTED = "on1y-glass-muted";

export function glassNavClass(selected: boolean, extra = ""): string {
  return `${selected ? GLASS_SELECTED : GLASS_IDLE}${extra ? ` ${extra}` : ""}`;
}
