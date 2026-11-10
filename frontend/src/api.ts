const API_BASE = "http://localhost:8000";

// Display name of the site a question was reported on (e.g. "Glassdoor"), or "generated".
export type QuestionSource = string;

export interface QuestionSourceInfo {
  source: QuestionSource;
  url: string;
}

export interface StartInterviewResponse {
  session_id: string;
  question: string;
  question_key: string;
  question_source: QuestionSource;
  question_url: string;
  company: string;
}

export interface AnswerResponse {
  status: "in_progress" | "awaiting_menu_choice" | "completed";
  question?: string;
  question_key?: string;
  question_source?: QuestionSource;
  question_url?: string;
  menu?: string[];
  result?: boolean;
  feedback_output?: string;
}

export async function startInterview(
  jobDescription: string,
  userId: string,
  company?: string
): Promise<StartInterviewResponse> {
  const res = await fetch(`${API_BASE}/interview/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      job_description: jobDescription,
      user_id: userId,
      company: company?.trim() || null,
    }),
  });
  if (!res.ok) throw new Error("Failed to start interview");
  return res.json();
}

export async function submitAnswer(
  sessionId: string,
  answer: string
): Promise<AnswerResponse> {
  const res = await fetch(`${API_BASE}/interview/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, answer }),
  });
  if (!res.ok) throw new Error("Failed to submit answer");
  return res.json();
}

export async function fetchSpeechAudioUrl(text: string): Promise<string> {
  const res = await fetch(`${API_BASE}/interview/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error("Failed to fetch speech audio");
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export interface JobSummary {
  jd_hash: string;
  job_description: string;
  attempt_count: number;
  last_attempt_at: number;
  last_result: boolean | null;
  company: string;
}

export interface Attempt {
  job_description: string;
  questions: Record<string, string>;
  question_sources: Record<string, QuestionSourceInfo>;
  company: string;
  responses: string[];
  feedback_output: string;
  result: boolean;
  timestamp: number;
}

export async function fetchJobs(userId: string): Promise<JobSummary[]> {
  const res = await fetch(`${API_BASE}/users/${encodeURIComponent(userId)}/jobs`);
  if (!res.ok) throw new Error("Failed to fetch jobs");
  return res.json();
}

export async function fetchAttempts(userId: string, jdHash: string): Promise<Attempt[]> {
  const res = await fetch(
    `${API_BASE}/users/${encodeURIComponent(userId)}/jobs/${jdHash}/attempts`
  );
  if (!res.ok) throw new Error("Failed to fetch attempts");
  return res.json();
}
