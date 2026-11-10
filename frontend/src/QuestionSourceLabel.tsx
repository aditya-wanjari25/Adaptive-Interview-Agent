import type { QuestionSource } from "./api";

// Attempts saved before open-web research stored lowercase source ids.
const LEGACY_SOURCE_NAMES: Record<string, string> = {
  glassdoor: "Glassdoor",
  blind: "Blind",
};

interface QuestionSourceLabelProps {
  source?: QuestionSource;
  url?: string;
}

export default function QuestionSourceLabel({ source, url }: QuestionSourceLabelProps) {
  if (!source || source === "generated") {
    return <span className="question-source">Generated from the job description</span>;
  }

  const name = LEGACY_SOURCE_NAMES[source] ?? source;
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
    </span>
  );
}
