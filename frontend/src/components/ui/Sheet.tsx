import type { HTMLAttributes, ReactNode } from "react";

interface SheetProps extends HTMLAttributes<HTMLElement> {
  as?: "section" | "article" | "div" | "aside";
  children: ReactNode;
}

/** A card: the base surface for every panel in SiteSense. */
export function Sheet({ as: Tag = "section", className = "", children, ...props }: SheetProps) {
  return (
    <Tag
      className={`relative rounded-[var(--radius-sheet)] border border-rule bg-paper-raised shadow-[var(--shadow-sheet)] ${className}`}
      {...props}
    >
      {children}
    </Tag>
  );
}
