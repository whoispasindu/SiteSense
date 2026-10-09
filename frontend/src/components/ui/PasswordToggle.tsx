export function PasswordToggle({ visible, onToggle }: { visible: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={visible}
      className="min-h-9 rounded-[2px] px-3 font-mono text-[0.68rem] tracking-wider text-ink-soft uppercase hover:bg-paper-sunk hover:text-ink"
    >
      {visible ? "Hide" : "Show"}
    </button>
  );
}
