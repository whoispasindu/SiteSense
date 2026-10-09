import type { ReactNode } from "react";

/** A small, consistent line-icon set (24px grid, 1.75 stroke). Icons are always decorative. */
const PATHS = {
  dashboard: <path d="M4 13h6V4H4v9Zm0 7h6v-4H4v4Zm10 0h6v-9h-6v9Zm0-16v4h6V4h-6Z" />,
  projects: <path d="M3 21h18M5 21V8l7-4 7 4v13M9 21v-6h6v6M9 10h.01M15 10h.01" />,
  schedule: <path d="M8 3v3m8-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm3 8h5m-5 4h8" />,
  reports: <path d="M9 4h6m-6 0a1 1 0 0 0-1 1v1h8V5a1 1 0 0 0-1-1M9 4H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2m-6 9 2 2 4-4" />,
  materials: <path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5v-9Zm0 0 9 4.5m0 0 9-4.5M12 12v9" />,
  risk: <path d="M12 3a9 9 0 0 0-9 9h3m6-9a9 9 0 0 1 9 9h-3m-6-9v3m0 6 4-4M12 12h.01" />,
  cost: <path d="M12 8c-2.2 0-4-.9-4-2s1.8-2 4-2 4 .9 4 2-1.8 2-4 2Zm-4-2v4c0 1.1 1.8 2 4 2s4-.9 4-2V6M8 10v4c0 1.1 1.8 2 4 2s4-.9 4-2v-4m-8 4v4c0 1.1 1.8 2 4 2s4-.9 4-2v-4" />,
  client: <path d="M16 19v-1a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v1M10 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm10 9v-1a4 4 0 0 0-3-3.9M15 4.1a3 3 0 0 1 0 5.8" />,
  users: <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0" />,
  sites: <path d="M12 21s-7-5.3-7-11a7 7 0 0 1 14 0c0 5.7-7 11-7 11Zm0-8a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" />,
  audit: <path d="M12 3 5 6v5c0 4.4 3 8.3 7 10 4-1.7 7-5.6 7-10V6l-7-3Zm-3 9 2 2 4-4" />,
  sun: <path d="M12 3v1.5M12 19.5V21M4.6 4.6l1.1 1.1m12.6 12.6 1.1 1.1M3 12h1.5m15 0H21M4.6 19.4l1.1-1.1M18.3 5.7l1.1-1.1M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z" />,
  moon: <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />,
  monitor: <path d="M4 5h16v11H4V5Zm4 15h8m-4-4v4" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  chevron: <path d="m9 6 6 6-6 6" />,
  upload: <path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />,
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof PATHS;

export function Icon({ name, className = "size-[18px]" }: { name: IconName; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {PATHS[name]}
    </svg>
  );
}
