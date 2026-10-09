export function LogoMark({ className = "size-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="5" fill="var(--color-hivis)" />
      <path d="M7 23h18" stroke="var(--color-asphalt)" strokeWidth="2.5" strokeLinecap="square" />
      <path d="M9 23V12l7-4 7 4v11" fill="none" stroke="var(--color-asphalt)" strokeWidth="2.5" />
      <path d="M14 23v-6h4v6" fill="var(--color-asphalt)" />
    </svg>
  );
}
