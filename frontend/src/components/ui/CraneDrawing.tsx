/** Line drawing of a tower crane over a building frame, with dimension marks. Decorative. */
export function CraneDrawing({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 420 360" className={className} aria-hidden="true" focusable="false" fill="none">
      {/* ground */}
      <path d="M0 340H420" stroke="currentColor" strokeWidth="1.5" />
      {/* building frame, five floors, two in progress */}
      <g stroke="currentColor" strokeWidth="1.2" opacity="0.8">
        <path d="M210 340V220H360V340" />
        <path d="M210 316H360M210 292H360M210 268H360M210 244H360" />
        <path d="M247.5 220V340M285 220V340M322.5 220V340" />
        <path d="M210 220V196H285" strokeDasharray="4 4" />
      </g>
      {/* crane mast */}
      <g stroke="currentColor" strokeWidth="1.2">
        <path d="M120 340V64M136 340V64" />
        {Array.from({ length: 11 }, (_, i) => (
          <path key={i} d={`M120 ${340 - i * 25}L136 ${315 - i * 25}`} />
        ))}
        <path d="M112 340H144" strokeWidth="3" />
        {/* cab and counter-jib */}
        <path d="M112 64H150V50H112Z" />
        <path d="M128 50L128 20" />
        <path d="M128 20L60 64M128 20L330 64" opacity="0.7" />
        <path d="M60 64H112" />
        <path d="M62 64V82H92V64" />
      </g>
      {/* jib in hi-vis */}
      <g stroke="var(--color-hivis)" strokeWidth="2">
        <path d="M150 58H372M150 64H372" />
        {Array.from({ length: 11 }, (_, i) => (
          <path key={i} d={`M${150 + i * 20} 64L${160 + i * 20} 58`} />
        ))}
      </g>
      {/* trolley, hook and load */}
      <g stroke="currentColor" strokeWidth="1.2">
        <path d="M296 64V176" strokeDasharray="2 3" />
        <path d="M288 176H304V186H288Z" fill="var(--color-hivis)" stroke="none" />
        <path d="M276 186H316V200H276Z" />
      </g>
      {/* dimension line */}
      <g stroke="currentColor" strokeWidth="1" opacity="0.6">
        <path d="M210 352H360M210 347V357M360 347V357" />
      </g>
      <text x="285" y="352" dy="-4" textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.7">
        24 000
      </text>
    </svg>
  );
}
