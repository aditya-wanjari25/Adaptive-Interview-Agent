import { useEffect, useRef, useState } from "react";
import VoiceOrb from "./VoiceOrb";
import Login from "./Login";
import Home from "./Home";
import JobsList from "./JobsList";
import JobDetail from "./JobDetail";
import Spinner from "./Spinner";
import LoadingDots from "./LoadingDots";
import {
  startInterview,
  submitAnswer,
  fetchSpeechAudioUrl,
  fetchJobs,
  fetchAttempts,
  type AnswerResponse,
  type JobSummary,
  type Attempt,
} from "./api";
import "./App.css";

type Phase = "login" | "home" | "jobs" | "job-detail" | "setup" | "question" | "menu" | "done";
type AnswerMode = "choose" | "typing" | "listening" | "reviewSpoken";

const USER_ID_KEY = "interview-coach:user-id";

function App() {
  const [phase, setPhase] = useState<Phase>("login");
  const [userId, setUserId] = useState<string | null>(null);

  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);

  const [selectedJobDescription, setSelectedJobDescription] = useState("");
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [attemptsLoading, setAttemptsLoading] = useState(false);

  const [jobDescription, setJobDescription] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [questionKey, setQuestionKey] = useState("");
  const [menu, setMenu] = useState<string[]>([]);
  const [result, setResult] = useState<boolean | undefined>();
  const [feedback, setFeedback] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const [answerMode, setAnswerMode] = useState<AnswerMode>("choose");
  const [typedAnswer, setTypedAnswer] = useState("");
  const [transcript, setTranscript] = useState("");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  const speechSupported =
    typeof window !== "undefined" &&
    (window.SpeechRecognition || window.webkitSpeechRecognition) != null;

  // resume login from a previous visit
  useEffect(() => {
    const savedUserId = localStorage.getItem(USER_ID_KEY);
    if (savedUserId) {
      setUserId(savedUserId);
      setPhase("home");
      loadJobs(savedUserId);
    }
  }, []);

  async function loadJobs(forUserId: string) {
    setJobsLoading(true);
    setErrorMsg(null);
    try {
      setJobs(await fetchJobs(forUserId));
    } catch {
      setErrorMsg("Couldn't load your practice history.");
    } finally {
      setJobsLoading(false);
    }
  }

  function handleLogin(username: string) {
    localStorage.setItem(USER_ID_KEY, username);
    setUserId(username);
    setPhase("home");
    loadJobs(username);
  }

  function handleLogout() {
    localStorage.removeItem(USER_ID_KEY);
    setUserId(null);
    setJobs([]);
    setPhase("login");
  }

  async function openJob(jdHash: string) {
    const job = jobs.find((j) => j.jd_hash === jdHash);
    if (!job || !userId) return;
    setSelectedJobDescription(job.job_description);
    setPhase("job-detail");
    setAttemptsLoading(true);
    setErrorMsg(null);
    try {
      setAttempts(await fetchAttempts(userId, jdHash));
    } catch {
      setErrorMsg("Couldn't load attempts for this job.");
    } finally {
      setAttemptsLoading(false);
    }
  }

  async function playQuestion(text: string) {
    try {
      const url = await fetchSpeechAudioUrl(text);
      const audio = audioRef.current;
      if (!audio) return;
      audio.src = url;
      await audio.play();
    } catch {
      // TTS is a nice-to-have; if it fails, the question text is still on screen.
      setErrorMsg("Couldn't play audio for this question, but you can still answer below.");
    }
  }

  function handleGraphResponse(res: AnswerResponse) {
    setErrorMsg(null);
    if (res.status === "in_progress") {
      setPhase("question");
      setAnswerMode("choose");
      setTypedAnswer("");
      setTranscript("");
      setQuestion(res.question ?? "");
      setQuestionKey(res.question_key ?? "");
      playQuestion(res.question ?? "");
    } else if (res.status === "awaiting_menu_choice") {
      setPhase("menu");
      setMenu(res.menu ?? []);
      setResult(res.result);
      setFeedback(res.feedback_output ?? "");
    } else {
      setPhase("done");
      setResult(res.result);
      setFeedback(res.feedback_output ?? "");
    }
  }

  async function beginInterview(jd: string) {
    if (!userId) return;
    setBusy(true);
    setErrorMsg(null);
    try {
      const res = await startInterview(jd, userId);
      setSessionId(res.session_id);
      setPhase("question");
      setAnswerMode("choose");
      setQuestion(res.question);
      setQuestionKey(res.question_key);
      await playQuestion(res.question);
    } catch {
      setErrorMsg("Couldn't start the interview. Is the backend running?");
    } finally {
      setBusy(false);
    }
  }

  function handleStartSubmit(e: React.FormEvent) {
    e.preventDefault();
    beginInterview(jobDescription);
  }

  async function sendAnswer(answer: string) {
    if (!sessionId || !answer.trim()) return;
    setBusy(true);
    setErrorMsg(null);
    try {
      const res = await submitAnswer(sessionId, answer);
      handleGraphResponse(res);
    } catch {
      setErrorMsg("Couldn't submit that answer. Try again.");
    } finally {
      setBusy(false);
    }
  }

  function startListening() {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Ctor) return;

    const recognition = new Ctor();
    recognition.lang = "en-US";
    recognition.continuous = true;
    recognition.interimResults = true;

    let finalTranscript = "";

    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const chunk = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += chunk + " ";
        } else {
          interim += chunk;
        }
      }
      setTranscript((finalTranscript + interim).trim());
    };

    recognition.onerror = () => {
      setErrorMsg("Speech recognition failed. Try typing your answer instead.");
      setAnswerMode("choose");
    };

    recognition.onend = () => {
      setAnswerMode((mode) => (mode === "listening" ? "reviewSpoken" : mode));
    };

    recognitionRef.current = recognition;
    setTranscript("");
    setAnswerMode("listening");
    recognition.start();
  }

  function stopListening() {
    recognitionRef.current?.stop();
  }

  const isLastQuestion = questionKey === "question5";
  const finalizing = busy && isLastQuestion;

  function goToJobs() {
    setPhase("jobs");
    setSessionId(null);
    if (userId) loadJobs(userId);
  }

  const audioEl = (
    <audio
      ref={audioRef}
      onPlay={() => setSpeaking(true)}
      onEnded={() => setSpeaking(false)}
      onPause={() => setSpeaking(false)}
    />
  );

  if (phase === "home" && userId) {
    return (
      <>
        {audioEl}
        <Home
          userId={userId}
          practiceCount={jobs.length}
          onStartNew={() => {
            setJobDescription("");
            setPhase("setup");
          }}
          onViewHistory={() => setPhase("jobs")}
          onLogout={handleLogout}
        />
      </>
    );
  }

  return (
    <div className="app">
      {audioEl}

      {phase !== "login" && (
        <div className="brand">
          <span className="brand-mark" />
          Interview Coach
        </div>
      )}

      {phase !== "login" && phase !== "jobs" && phase !== "job-detail" && (
        <VoiceOrb speaking={speaking || finalizing} />
      )}

      {errorMsg && <p className="error">{errorMsg}</p>}

      {phase === "login" && <Login onLogin={handleLogin} />}

      {phase === "jobs" && (
        <JobsList
          jobs={jobs}
          loading={jobsLoading}
          onSelectJob={openJob}
          onNewInterview={() => {
            setJobDescription("");
            setPhase("setup");
          }}
          onBackHome={() => setPhase("home")}
          onLogout={handleLogout}
        />
      )}

      {phase === "job-detail" && (
        <JobDetail
          jobDescription={selectedJobDescription}
          attempts={attempts}
          loading={attemptsLoading}
          onBack={() => setPhase("jobs")}
          onPracticeAgain={() => beginInterview(selectedJobDescription)}
        />
      )}

      {phase === "setup" && (
        <form className="panel" onSubmit={handleStartSubmit}>
          <div className="row-between">
            <h1>Start Interview</h1>
            <button type="button" className="ghost" onClick={() => setPhase("home")}>
              Cancel
            </button>
          </div>
          <label>
            Job description
            <textarea
              value={jobDescription}
              onChange={(e) => setJobDescription(e.target.value)}
              rows={8}
              placeholder="Paste the job description here..."
              required
              autoFocus
            />
          </label>
          <button type="submit" disabled={busy}>
            {busy ? "Starting..." : "Start Interview"}
          </button>
        </form>
      )}

      {phase === "question" && (
        <div className="panel">
          {finalizing ? (
            <div className="loading-panel">
              <p>
                Generating your feedback
                <LoadingDots />
              </p>
              <p className="loading-subtext">This takes a few seconds — analyzing all 5 answers.</p>
            </div>
          ) : (
            <>
              <p className="question">{question}</p>

              {answerMode === "choose" && (
                <div className="choice-row">
                  <button onClick={() => setAnswerMode("typing")} disabled={busy}>
                    Type Answer
                  </button>
                  <button
                    onClick={startListening}
                    disabled={busy || !speechSupported}
                    title={speechSupported ? "" : "Speech recognition isn't supported in this browser"}
                  >
                    Speak Answer
                  </button>
                </div>
              )}

              {answerMode === "typing" && (
                <div className="answer-block">
                  <textarea
                    value={typedAnswer}
                    onChange={(e) => setTypedAnswer(e.target.value)}
                    rows={5}
                    placeholder="Type your answer..."
                    autoFocus
                  />
                  <button onClick={() => sendAnswer(typedAnswer)} disabled={busy || !typedAnswer.trim()}>
                    {busy ? (
                      <>
                        <Spinner /> Submitting
                      </>
                    ) : (
                      "Submit"
                    )}
                  </button>
                </div>
              )}

              {answerMode === "listening" && (
                <div className="answer-block">
                  <p className="transcript listening">Listening... {transcript}</p>
                  <button onClick={stopListening}>Done Speaking</button>
                </div>
              )}

              {answerMode === "reviewSpoken" && (
                <div className="answer-block">
                  <textarea
                    value={transcript}
                    onChange={(e) => setTranscript(e.target.value)}
                    rows={5}
                  />
                  <div className="choice-row">
                    <button onClick={() => sendAnswer(transcript)} disabled={busy || !transcript.trim()}>
                      {busy ? (
                        <>
                          <Spinner /> Submitting
                        </>
                      ) : (
                        "Submit"
                      )}
                    </button>
                    <button onClick={startListening} disabled={busy}>
                      Re-record
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {phase === "menu" && (
        <div className="panel">
          <h2>{result ? "You passed this round" : "Not quite there yet"}</h2>
          <pre className="feedback">{feedback}</pre>
          <div className="choice-row">
            {menu.map((choice) => (
              <button key={choice} onClick={() => sendAnswer(choice)} disabled={busy}>
                {choice === "practice_again" ? "Practice Again" : "Exit"}
              </button>
            ))}
          </div>
        </div>
      )}

      {phase === "done" && (
        <div className="panel">
          <h2>{result ? "You passed this round" : "Not quite there yet"}</h2>
          <pre className="feedback">{feedback}</pre>
          <div className="choice-row">
            <button onClick={goToJobs}>Back to Jobs</button>
            <button
              onClick={() => {
                setJobDescription("");
                setPhase("setup");
              }}
            >
              Start New Interview
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
