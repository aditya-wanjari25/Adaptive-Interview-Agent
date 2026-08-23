interface HomeProps {
  userId: string;
  practiceCount: number;
  onStartNew: () => void;
  onViewHistory: () => void;
  onLogout: () => void;
}

const FEATURES = [
  {
    icon: (
      <path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z" />
    ),
    title: "Real questions, spoken aloud",
    body: "Get 5 screening questions generated from any job description, read aloud by an AI voice.",
  },
  {
    icon: (
      <path d="M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm1 2v10h14V7H5Zm2 2h2v2H7V9Zm4 0h2v2h-2V9Zm4 0h2v2h-2V9ZM7 13h10v2H7v-2Z" />
    ),
    title: "Speak or type your answer",
    body: "Talk it out like a real interview, or type if you'd rather write. Either way works.",
  },
  {
    icon: (
      <path d="M4 19h16v2H4v-2Zm1-5 4-5 3 3 5-6 4 5-1.5 1.2L16 9.3l-5 6-3-3-3.6 4.5L4 15Z" />
    ),
    title: "Feedback that remembers",
    body: "Come back and practice the same job again — your coach compares your new answers to your last attempt.",
  },
];

export default function Home({
  userId,
  practiceCount,
  onStartNew,
  onViewHistory,
  onLogout,
}: HomeProps) {
  return (
    <div className="landing">
      <header className="landing-nav">
        <div className="landing-nav-inner">
          <div className="brand">
            <span className="brand-mark" />
            Interview Coach
          </div>
          <nav className="landing-nav-links">
            <button className="ghost" onClick={onViewHistory}>
              Practice History
            </button>
            <span className="landing-user">{userId}</span>
            <button className="ghost" onClick={onLogout}>
              Log out
            </button>
          </nav>
        </div>
      </header>

      <main>
        <section className="landing-hero">
          <h1 className="landing-hero-title">Practice interviews with a coach that remembers</h1>
          <p className="landing-hero-subtitle">
            Paste a job description, answer 5 AI-generated screening questions out loud or in writing, and
            get direct, specific feedback — then come back and improve on the exact same questions.
          </p>
          <div className="choice-row hero-actions">
            <button onClick={onStartNew}>Start New Interview</button>
            <button className="outline" onClick={onViewHistory}>
              View Your Practice History
              {practiceCount > 0 ? ` (${practiceCount})` : ""}
            </button>
          </div>
        </section>

        <hr className="landing-divider" />

        <section className="landing-features">
          {FEATURES.map((f) => (
            <div key={f.title} className="landing-feature">
              <div className="landing-feature-icon">
                <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true">
                  {f.icon}
                </svg>
              </div>
              <h3 className="landing-feature-title">{f.title}</h3>
              <p className="landing-feature-body">{f.body}</p>
            </div>
          ))}
        </section>
      </main>

      <footer className="landing-footer">
        <p>Interview Coach &mdash; practice smarter, not just harder.</p>
      </footer>
    </div>
  );
}
