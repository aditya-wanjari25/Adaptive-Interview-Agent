import type { QuestionSource } from "./api";

// Attempts saved before open-web research stored lowercase source ids.
const LEGACY_SOURCE_NAMES: Record<string, string> = {
  glassdoor: "Glassdoor",
  blind: "Blind",
};

interface QuestionSourceLabelProps {
  source?: QuestionSource;
  url?: string;
  reportedDate?: string; // "YYYY-MM" or "YYYY"
}

function formatReportedDate(value?: string): string | null {
  if (!value) return null;
  const match = /^(\d{4})(?:-(\d{2}))?$/.exec(value);
  if (!match) return null;
  const [, year, month] = match;
  if (!month) return year;
  return new Date(Number(year), Number(month) - 1).toLocaleString(undefined, {
    month: "short",
    year: "numeric",
  });
}

export default function QuestionSourceLabel({ source, url, reportedDate }: QuestionSourceLabelProps) {
  if (!source || source === "generated") {
    return <span className="question-source">Generated from the job description</span>;
  }

  const name = LEGACY_SOURCE_NAMES[source] ?? source;
  const date = formatReportedDate(reportedDate);
  return (
    <span className="question-source reported">
      Reported by candidates on{" "}
      {url ? (
        <a href={url} target="_blank" rel="noopener noreferrer">
          {name}
        </a>
      ) : (
        name
      )}
      {date && <> &middot; {date}</>}
    </span>
  );
}
