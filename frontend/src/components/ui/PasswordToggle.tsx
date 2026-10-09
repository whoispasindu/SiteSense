export function PasswordToggle({ visible, onToggle }: { visible: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={visible}
      className="min-h-8 rounded-md px-2.5 text-sm font-medium text-ink-soft hover:bg-paper-sunk hover:text-ink"
    >
      {visible ? "Hide" : "Show"}
    </button>
  );
}
