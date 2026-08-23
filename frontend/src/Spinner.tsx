export default function Spinner() {
  return (
    <svg className="spinner" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <circle
        className="spinner-track"
        cx="12"
        cy="12"
        r="9"
        fill="none"
        strokeWidth="3"
      />
      <circle
        className="spinner-head"
        cx="12"
        cy="12"
        r="9"
        fill="none"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}
