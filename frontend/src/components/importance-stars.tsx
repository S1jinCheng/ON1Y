"use client";

import { Star } from "lucide-react";

type ImportanceStarsProps = {
  value: number | null | undefined;
  onChange?: (value: number | null) => void;
  readonly?: boolean;
  size?: "sm" | "md";
  ariaLabel?: string;
};

const SIZE_CLASS = {
  sm: "h-3 w-3",
  md: "h-4 w-4"
} as const;

export function ImportanceStars(props: ImportanceStarsProps): JSX.Element {
  const { value, onChange, readonly = false, size = "md", ariaLabel } = props;
  const current = value && value >= 1 && value <= 5 ? value : 0;

  return (
    <div
      className="inline-flex items-center gap-0.5"
      role={readonly ? "img" : "group"}
      aria-label={ariaLabel}
    >
      {[1, 2, 3, 4, 5].map((star) => {
        const filled = star <= current;
        if (readonly || !onChange) {
          return (
            <Star
              key={star}
              className={`${SIZE_CLASS[size]} ${filled ? "fill-amber-400 text-amber-500" : "text-muted/30"}`}
              aria-hidden
            />
          );
        }
        return (
          <button
            key={star}
            type="button"
            className="rounded p-0.5 text-muted transition-colors hover:text-amber-500"
            aria-label={`${star} star${star > 1 ? "s" : ""}`}
            aria-pressed={filled}
            onClick={() => onChange(star === current ? null : star)}
          >
            <Star
              className={`${SIZE_CLASS[size]} ${filled ? "fill-amber-400 text-amber-500" : ""}`}
            />
          </button>
        );
      })}
    </div>
  );
}
