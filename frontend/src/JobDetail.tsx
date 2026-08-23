import type { Attempt } from "./api";

interface JobDetailProps {
  jobDescription: string;
  attempts: Attempt[];
  loading: boolean;
  onBack: () => void;
  onPracticeAgain: () => void;
}

export default function JobDetail({
  jobDescription,
  attempts,
  loading,
  onBack,
  onPracticeAgain,
}: JobDetailProps) {
  return (
    <div className="panel">
      <button className="ghost" onClick={onBack}>
        &larr; Back to jobs
      </button>

      <h2>Job Description</h2>
      <p className="job-desc-full">{jobDescription}</p>

      <button onClick={onPracticeAgain}>Practice This Job Again</button>

      {loading && <p className="muted">Loading attempts...</p>}

      {attempts.map((attempt, idx) => {
        const questions = Object.values(attempt.questions);
        return (
          <details key={attempt.timestamp} className="attempt" open={idx === 0}>
            <summary>
              {new Date(attempt.timestamp * 1000).toLocaleString()} &mdash;{" "}
              <span className={`badge ${attempt.result ? "pass" : "fail"}`}>
                {attempt.result ? "Passed" : "Not yet"}
              </span>
            </summary>
            <div className="attempt-body">
              <h3>Feedback</h3>
              <pre className="feedback">{attempt.feedback_output}</pre>

              <h3>Responses</h3>
              {questions.map((question, i) => (
                <div key={i} className="qa-pair">
                  <p className="qa-question">{question}</p>
                  <p className="qa-answer">{attempt.responses[i]}</p>
                </div>
              ))}
            </div>
          </details>
        );
      })}
    </div>
  );
}
